"""End-to-end pipeline: crawl -> filter -> enrich -> score -> group.

The pipeline is also what the desktop app drives, so :func:`run` takes two
optional hooks the command line never passes:

``progress``
    Called as ``progress(stage, done, total, message)`` whenever the run
    moves forward.  ``total`` is 0 while a stage's size is still unknown.
``cancel``
    A :class:`threading.Event`.  When it is set the run stops at the next
    checkpoint and raises :class:`Cancelled` — half a crawl is never
    returned as if it were a whole one.
``on_fetcher``
    Handed the :class:`~fnscraper.http.Fetcher` as soon as it exists, so a
    caller can read its live request counters while the run is going.  The
    run builds its own Fetcher from ``settings``; this is the only way to
    reach it without duplicating that construction.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Callable

from . import categories, config, parse
from .geocode import Geocoder, drive_estimate
from .http import Fetcher
from .models import Event, ScoredEvent
from .scoring import score_event

log = logging.getLogger(__name__)

# progress(stage, done, total, message)
ProgressFn = Callable[[str, int, int, str], None]

STAGES = ("login", "crawl", "filter", "geocode", "detail", "score")


class Cancelled(RuntimeError):
    """Raised by :func:`run` when its ``cancel`` event is set."""


def _noop(stage: str, done: int, total: int, message: str) -> None:
    pass


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("scrape cancelled")


def crawl_state(
    fetcher: Fetcher,
    state: str,
    until: date,
    max_pages: int,
    cancel: threading.Event | None = None,
) -> list[Event]:
    """Walk a state's listing pages until events start past ``until``.

    Listing pages are sorted by start date, so we can stop as soon as a
    full page falls beyond the horizon.
    """
    events: list[Event] = []
    for page in range(1, max_pages + 1):
        _check(cancel)
        url = f"{config.BASE_URL}/fairs-festivals/{state}"
        if page > 1:
            url += f"?page={page}"
        try:
            html = fetcher.get(url)
        except Exception as exc:
            log.warning("Skipping %s page %s: %s", state, page, exc)
            break
        page_events = parse.parse_listing_page(html)
        if not page_events:
            break
        events.extend(page_events)
        dated = [e.start_date for e in page_events if e.start_date]
        if dated and min(dated) > until:
            break
        if not parse.listing_has_next_page(html, page):
            break
    log.info("%s: %d listings collected", state, len(events))
    return events


def _strip_private_fields(event: Event, settings: config.Settings) -> None:
    """Drop detail fields the caller asked not to collect.

    Contact details and real booth fees are the two things a Pro login
    exposes, and the desktop app lets you say "crawl, but don't keep the
    promoter's phone number".  Honour that by clearing the fields before
    anything downstream (scoring, exports, the saved results file) sees
    them.
    """
    if not settings.include_contact:
        event.contact_name = ""
        event.contact_email = ""
        event.contact_phone = ""
        event.promoter_website = ""
    if not settings.include_fees:
        event.exhib_fee = None
        event.food_fee = None
        event.booth_fee_text = ""


def run(
    settings: config.Settings,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    on_fetcher: Callable[[Fetcher], None] | None = None,
) -> list[ScoredEvent]:
    report = progress or _noop
    today = date.today()
    horizon = today + timedelta(weeks=settings.weeks_ahead)

    jobs = max(1, settings.jobs)
    fetcher = Fetcher(
        cache_dir=settings.cache_dir,
        delay=settings.request_delay,
        refresh=settings.refresh,
        workers=jobs,
        max_retries=settings.max_retries,
    )
    if on_fetcher is not None:
        on_fetcher(fetcher)
    if settings.username and settings.password:
        report("login", 0, 1, "Signing in to FestivalNet…")
        fetcher.login(settings.username, settings.password)
        report("login", 1, 1,
               "Signed in" if fetcher.logged_in else "Continuing anonymously")

    geocoder = Geocoder(settings.geocode_cache)

    # 1. Crawl listings for every candidate state.  Each state walks its own
    #    pages sequentially, but different states are independent, so we run
    #    up to `jobs` of them at once.  First-writer-wins de-dup below keeps
    #    the result order-independent.
    _check(cancel)
    states = list(settings.states)
    report("crawl", 0, len(states), f"Crawling {len(states)} state listings…")
    seen: dict[str, Event] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(
                crawl_state, fetcher, st, horizon,
                settings.max_pages_per_state, cancel,
            ): st
            for st in states
        }
        try:
            for fut in as_completed(futures):
                state = futures[fut]
                try:
                    events = fut.result()
                except Cancelled:
                    raise
                except Exception as exc:
                    log.warning("Crawl failed for %s: %s", state, exc)
                    events = []
                for ev in events:
                    seen.setdefault(ev.event_id, ev)
                done += 1
                report("crawl", done, len(states),
                       f"{state.replace('-', ' ')}: {len(seen):,} listings so far")
        except Cancelled:
            pool.shutdown(wait=False, cancel_futures=True)
            raise

    # 1b. Drop unwanted categories (e.g. fairs) up front so we never spend
    #     geocoding or detail-fetch budget on shows the vendor won't work.
    _check(cancel)
    if settings.categories is not None:
        before = len(seen)
        seen = {
            eid: ev for eid, ev in seen.items()
            if categories.category_key(ev.category_slug) in settings.categories
        }
        log.info("category filter kept %d of %d listings (%s)",
                 len(seen), before, ", ".join(sorted(settings.categories)))

    # 2. Keep events inside the date window.
    upcoming = [
        e for e in seen.values()
        if e.start_date and today <= e.start_date <= horizon
    ]
    log.info("%d unique events within the next %d weeks",
             len(upcoming), settings.weeks_ahead)
    report("filter", len(upcoming), len(seen),
           f"{len(upcoming):,} events inside the date window")

    # 3. Rough distance pre-filter on city coordinates so we don't fetch
    #    detail pages for events obviously out of range.
    #
    #    Geocoding is the slow stage: Nominatim is rate-limited to ~1 req/s.
    #    Hundreds of events share a handful of cities, so we resolve each
    #    distinct (city, state) once and fan the result back out to every
    #    event there.  This makes the loop iterate real network work (one
    #    tick per city) instead of racing through cache hits and then
    #    appearing to stall on the first uncached city.
    if not settings.geocode:
        in_range = upcoming
        report("geocode", 1, 1, "Distance filter off — keeping every event")
    else:
        by_city: dict[tuple[str, str], list[Event]] = {}
        for ev in upcoming:
            by_city.setdefault((ev.city, ev.state), []).append(ev)
        log.info("geocoding %d distinct cities across %d events",
                 len(by_city), len(upcoming))
        report("geocode", 0, len(by_city),
               f"Locating {len(by_city):,} cities…")

        in_range = []
        for i, ((city, state), evs) in enumerate(by_city.items(), 1):
            _check(cancel)
            lat, lon, approx = geocoder.locate(city, state)
            miles, hours = drive_estimate(lat, lon)
            # Give state-centroid approximations 25% slack before discarding.
            limit = settings.max_drive_hours * (1.25 if approx else 1.0)
            for ev in evs:
                ev.lat, ev.lon = lat, lon
                ev.distance_miles, ev.drive_hours = miles, hours
                if hours <= limit:
                    in_range.append(ev)
            report("geocode", i, len(by_city),
                   f"{city}, {state} — {len(in_range):,} events in range")
            if i % 50 == 0:
                log.info("geocoding: %d/%d cities (%d events in range so far)",
                         i, len(by_city), len(in_range))
        geocoder.flush()
        log.info("%d events within ~%.0f h drive of %s",
                 len(in_range), settings.max_drive_hours, config.HOME_NAME)

    # 4a. Fetch + parse detail pages for the survivors (attendance,
    #     exhibitors, admission, street address — and real fees when logged
    #     in).  Fetching is the bulk of the run and every event is
    #     independent, so we fan out across `jobs` workers.  parse_detail_page
    #     only mutates its own event, so the threads never touch shared state.
    def _enrich(ev: Event) -> None:
        _check(cancel)
        html = fetcher.get(ev.url)
        parse.parse_detail_page(html, ev)
        _strip_private_fields(ev, settings)

    if settings.scrape_details:
        report("detail", 0, len(in_range),
               f"Reading {len(in_range):,} event pages…")
        done = 0
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_enrich, ev): ev for ev in in_range}
            try:
                for fut in as_completed(futures):
                    ev = futures[fut]
                    try:
                        fut.result()
                    except Cancelled:
                        raise
                    except Exception as exc:
                        log.warning("Detail fetch failed for %s: %s", ev.url, exc)
                    done += 1
                    report("detail", done, len(in_range), ev.name)
                    if done % 25 == 0:
                        log.info("detail pages: %d/%d", done, len(in_range))
            except Cancelled:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
    else:
        report("detail", 0, 0, "Detail pages skipped")

    # 4b. Re-locate events that exposed a street address, using its ZIP for a
    #     tighter drive estimate.  Kept sequential: Nominatim/zippopotam.us
    #     enforce ~1 req/s and the Geocoder cache/state is not thread-safe.
    if settings.geocode:
        for ev in in_range:
            _check(cancel)
            # Anonymous listings put the whole mailing line in `address`; Pro
            # pages give the street alone and the ZIP up in the header block.
            # Join them so both layouts get the tighter ZIP-based fix.
            locator = " ".join(x for x in (ev.address, ev.zip_code) if x)
            if locator:
                lat, lon, approx = geocoder.locate(ev.city, ev.state, locator)
                if not approx:
                    ev.lat, ev.lon = lat, lon
                    ev.distance_miles, ev.drive_hours = drive_estimate(lat, lon)

    # 5. Final hard distance filter, then score.
    _check(cancel)
    report("score", 0, len(in_range), "Scoring events…")
    scored = [
        score_event(ev)
        for ev in in_range
        if not settings.geocode
        or (ev.drive_hours is not None and ev.drive_hours <= settings.max_drive_hours)
    ]
    scored.sort(key=lambda s: s.breakdown.score, reverse=True)
    stats = fetcher.stats()
    report("score", len(scored), len(scored),
           f"{len(scored):,} events scored "
           f"({stats['requests']:,} requests, {stats['failures']:,} failed)")
    return scored


def group_by_weekend(scored: list[ScoredEvent]) -> dict[date, list[ScoredEvent]]:
    """Group scored events by the Saturday of their weekend.

    Events starting Mon-Thu that do not touch a weekend are grouped under
    the following weekend so nothing silently disappears from the report.
    """
    weekends: dict[date, list[ScoredEvent]] = {}
    for s in scored:
        key = s.weekend_key
        if key is None:
            continue
        weekends.setdefault(key, []).append(s)
    for group in weekends.values():
        group.sort(key=lambda s: s.breakdown.score, reverse=True)
    return dict(sorted(weekends.items()))

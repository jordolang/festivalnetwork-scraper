"""End-to-end pipeline: crawl -> filter -> enrich -> score -> group."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from . import config, parse
from .geocode import Geocoder, drive_estimate
from .http import Fetcher
from .models import Event, ScoredEvent
from .scoring import score_event

log = logging.getLogger(__name__)


def crawl_state(fetcher: Fetcher, state: str, until: date, max_pages: int) -> list[Event]:
    """Walk a state's listing pages until events start past ``until``.

    Listing pages are sorted by start date, so we can stop as soon as a
    full page falls beyond the horizon.
    """
    events: list[Event] = []
    for page in range(1, max_pages + 1):
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


def run(settings: config.Settings) -> list[ScoredEvent]:
    today = date.today()
    horizon = today + timedelta(weeks=settings.weeks_ahead)

    fetcher = Fetcher(cache_dir=settings.cache_dir, refresh=settings.refresh)
    if settings.username and settings.password:
        fetcher.login(settings.username, settings.password)

    geocoder = Geocoder(settings.geocode_cache)

    # 1. Crawl listings for every candidate state.
    seen: dict[str, Event] = {}
    for state in settings.states:
        for ev in crawl_state(fetcher, state, horizon, settings.max_pages_per_state):
            seen.setdefault(ev.event_id, ev)

    # 2. Keep events inside the date window.
    upcoming = [
        e for e in seen.values()
        if e.start_date and today <= e.start_date <= horizon
    ]
    log.info("%d unique events within the next %d weeks",
             len(upcoming), settings.weeks_ahead)

    # 3. Rough distance pre-filter on city coordinates so we don't fetch
    #    detail pages for events obviously out of range.
    #
    #    Geocoding is the slow stage: Nominatim is rate-limited to ~1 req/s.
    #    Hundreds of events share a handful of cities, so we resolve each
    #    distinct (city, state) once and fan the result back out to every
    #    event there.  This makes the loop iterate real network work (one
    #    tick per city) instead of racing through cache hits and then
    #    appearing to stall on the first uncached city.
    by_city: dict[tuple[str, str], list[Event]] = {}
    for ev in upcoming:
        by_city.setdefault((ev.city, ev.state), []).append(ev)
    log.info("geocoding %d distinct cities across %d events",
             len(by_city), len(upcoming))

    in_range: list[Event] = []
    for i, ((city, state), evs) in enumerate(by_city.items(), 1):
        lat, lon, approx = geocoder.locate(city, state)
        miles, hours = drive_estimate(lat, lon)
        # Give state-centroid approximations 25% slack before discarding.
        limit = settings.max_drive_hours * (1.25 if approx else 1.0)
        for ev in evs:
            ev.lat, ev.lon = lat, lon
            ev.distance_miles, ev.drive_hours = miles, hours
            if hours <= limit:
                in_range.append(ev)
        if i % 50 == 0:
            log.info("geocoding: %d/%d cities (%d events in range so far)",
                     i, len(by_city), len(in_range))
    geocoder.flush()
    log.info("%d events within ~%.0f h drive of %s",
             len(in_range), settings.max_drive_hours, config.HOME_NAME)

    # 4. Fetch detail pages for the survivors (attendance, exhibitors,
    #    admission, street address — and real fees when logged in).
    for i, ev in enumerate(in_range, 1):
        try:
            html = fetcher.get(ev.url)
            parse.parse_detail_page(html, ev)
        except Exception as exc:
            log.warning("Detail fetch failed for %s: %s", ev.url, exc)
            continue
        if ev.address:
            # Re-locate with the street address ZIP for a tighter estimate.
            lat, lon, approx = geocoder.locate(ev.city, ev.state, ev.address)
            if not approx:
                ev.lat, ev.lon = lat, lon
                ev.distance_miles, ev.drive_hours = drive_estimate(lat, lon)
        if i % 25 == 0:
            log.info("detail pages: %d/%d", i, len(in_range))

    # 5. Final hard distance filter, then score.
    scored = [
        score_event(ev)
        for ev in in_range
        if ev.drive_hours is not None and ev.drive_hours <= settings.max_drive_hours
    ]
    scored.sort(key=lambda s: s.breakdown.score, reverse=True)
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

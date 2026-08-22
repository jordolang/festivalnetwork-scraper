"""Runs the crawl off the UI thread and reports back through a queue.

Tk is single-threaded: touching a widget from a worker thread corrupts the
interpreter, usually much later and somewhere unrelated.  So the worker
only ever puts messages on a queue, and the window drains that queue from
its own event loop.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from .. import categories, config
from . import places

# (kind, payload) pairs the window knows how to handle.
PROGRESS = "progress"
FINISHED = "finished"
FAILED = "failed"
CANCELLED = "cancelled"


@dataclass
class CrawlOptions:
    """The rail's crawl settings — what to fetch, and how politely."""

    country: str = places.ALL_COUNTRIES
    state: str = ""                 # "" means every state in the country
    event_type: str = ""            # "" means every category but fairs
    date_from: date | None = None
    date_to: date | None = None
    use_dates: bool = True
    max_drive_hours: float | None = None

    all_pages: bool = True
    delay: float = config.REQUEST_DELAY_SECONDS
    jobs: int = config.DEFAULT_JOBS
    retry_failed: bool = True
    scrape_details: bool = True
    geocode: bool = True
    include_contact: bool = True
    include_fees: bool = True
    refresh_cache: bool = False
    output_dir: str = "reports"
    cache_dir: str = "data/cache"
    geocode_cache: str = "data/geocode_cache.json"

    username: str | None = None
    password: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def weeks_between(start: date | None, end: date | None) -> int:
    """Whole weeks from today to ``end``, which is what the crawl bounds by.

    The pipeline's horizon is "weeks from today", so a date range that
    starts in the future still has to be crawled from today — the range's
    start is applied afterwards as a filter, not as a crawl bound.
    """
    if end is None:
        return 8
    span = (end - date.today()).days
    return max(1, -(-span // 7))       # ceiling division


def states_for(options: CrawlOptions) -> list[str]:
    """The listing-page slugs to crawl."""
    if options.state:
        place = places.by_label(options.state) or places.by_code(options.state)
        if place is not None:
            return [place.slug]
    if options.country == places.ALL_COUNTRIES:
        # No country chosen: keep the shipped shortlist, which is already
        # "states a day's drive from home" rather than all fifty.
        return list(config.DEFAULT_STATES)
    return [p.slug for p in places.places_for(options.country)]


def categories_for(options: CrawlOptions) -> set[str]:
    if options.event_type:
        return {options.event_type}
    return categories.default_selection()


def settings_for(options: CrawlOptions) -> config.Settings:
    """Turn the rail's controls into a :class:`config.Settings`."""
    settings = config.Settings.from_env(
        weeks_ahead=weeks_between(options.date_from, options.date_to)
        if options.use_dates else 8,
        output_dir=options.output_dir,
        refresh=options.refresh_cache,
        jobs=max(1, int(options.jobs)),
        max_pages_per_state=config.MAX_PAGES_PER_STATE if options.all_pages else 1,
        request_delay=max(0.0, float(options.delay)),
        max_retries=3 if options.retry_failed else 1,
        scrape_details=options.scrape_details,
        geocode=options.geocode,
        include_contact=options.include_contact,
        include_fees=options.include_fees,
    )
    settings.cache_dir = options.cache_dir
    settings.geocode_cache = options.geocode_cache
    settings.states = states_for(options)
    settings.categories = categories_for(options)
    if options.max_drive_hours:
        settings.max_drive_hours = float(options.max_drive_hours)
    if options.username:
        settings.username = options.username
    if options.password:
        settings.password = options.password
    return settings


@dataclass
class Progress:
    stage: str = ""
    done: int = 0
    total: int = 0
    message: str = ""
    elapsed: float = 0.0
    requests: int = 0
    failures: int = 0

    @property
    def fraction(self) -> float:
        return 0.0 if self.total <= 0 else min(1.0, self.done / self.total)


class ScrapeController:
    """Starts, stops and reports on one crawl at a time."""

    def __init__(self, sink: Callable[[str, Any], None]):
        self.sink = sink
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._started_at = 0.0
        self.last_error: str | None = None

    # -- state ---------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self) -> float:
        return 0.0 if not self._started_at else time.monotonic() - self._started_at

    # -- control -------------------------------------------------------
    def start(self, settings: config.Settings,
              results_path: Path | None = None) -> bool:
        if self.running:
            return False
        self._cancel = threading.Event()
        self._started_at = time.monotonic()
        self.last_error = None
        self._thread = threading.Thread(
            target=self._run, args=(settings, results_path),
            name="fnscraper-crawl", daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._cancel.set()

    @property
    def stopping(self) -> bool:
        return self._cancel.is_set() and self.running

    def _run(self, settings: config.Settings, results_path: Path | None):
        # Imported here, not at module scope: the window must open on a
        # machine where `requests` was never installed, and say so, rather
        # than failing to start at all.
        from .. import persist, pipeline

        def report(stage: str, done: int, total: int, message: str):
            self.queue.put((PROGRESS, Progress(
                stage=stage, done=done, total=total, message=message,
                elapsed=self.elapsed,
            )))

        try:
            scored = pipeline.run(settings, progress=report, cancel=self._cancel)
        except pipeline.Cancelled:
            self.queue.put((CANCELLED, None))
            return
        except Exception as exc:                  # surfaced in the status bar
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.queue.put((FAILED, self.last_error))
            return

        saved: Path | None = None
        if results_path is not None:
            try:
                saved = persist.save_results(scored, results_path)
            except OSError as exc:
                self.queue.put((PROGRESS, Progress(
                    stage="save", message=f"Could not save results: {exc}",
                    elapsed=self.elapsed,
                )))
        self.queue.put((FINISHED, {"scored": scored, "path": saved,
                                   "elapsed": self.elapsed}))

    # -- pumping -------------------------------------------------------
    def drain(self) -> None:
        """Deliver every queued message.  Call from the Tk event loop."""
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                return
            self.sink(kind, payload)


def default_results_path(output_dir: str | Path = "reports") -> Path:
    return Path(output_dir) / "results.json"


def timestamped_export_stem(when: date | None = None) -> str:
    when = when or date.today()
    return f"festivals-{when:%Y-%m-%d}"


def format_elapsed(seconds: float) -> str:
    seconds = int(max(0.0, seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def default_date_range() -> tuple[date, date]:
    """Today through a year out — the mockup's 12-month window."""
    today = date.today()
    return today, today + timedelta(days=365)

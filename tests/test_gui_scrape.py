"""The desktop app's crawl plumbing: settings mapping, counters, cancelling."""

from __future__ import annotations

import pathlib
import threading
from datetime import date, timedelta

import pytest

from fnscraper import categories, config, pipeline
from fnscraper.gui import places, scrape
from fnscraper.http import Fetcher
from fnscraper.models import Event


# ---------------------------------------------------------------------------
# rail settings -> config.Settings
# ---------------------------------------------------------------------------

def test_a_chosen_state_narrows_the_crawl_to_its_listing_slug():
    options = scrape.CrawlOptions(country=places.UNITED_STATES,
                                  state="West Virginia (WV)")
    assert scrape.states_for(options) == ["West-Virginia"]


def test_a_country_with_no_state_crawls_every_place_in_it():
    slugs = scrape.states_for(scrape.CrawlOptions(country=places.CANADA))
    assert "Ontario" in slugs and len(slugs) == len(places.CA_PROVINCES)


def test_no_country_keeps_the_shipped_state_shortlist():
    options = scrape.CrawlOptions(country=places.ALL_COUNTRIES)
    assert scrape.states_for(options) == config.DEFAULT_STATES


def test_no_event_type_uses_the_default_selection_which_drops_fairs():
    selected = scrape.categories_for(scrape.CrawlOptions())
    assert selected == categories.default_selection()
    assert "fair" not in selected


def test_one_event_type_crawls_only_that_category():
    assert scrape.categories_for(scrape.CrawlOptions(event_type="food")) == {"food"}


def test_weeks_between_rounds_up_to_cover_the_whole_range():
    today = date.today()
    assert scrape.weeks_between(today, today + timedelta(days=14)) == 2
    assert scrape.weeks_between(today, today + timedelta(days=15)) == 3
    assert scrape.weeks_between(today, today) == 1
    assert scrape.weeks_between(None, None) == 8


def test_switches_reach_the_settings_the_pipeline_reads():
    options = scrape.CrawlOptions(
        all_pages=False, delay=0.25, jobs=9, retry_failed=False,
        scrape_details=False, geocode=False, include_contact=False,
        include_fees=False, refresh_cache=True, max_drive_hours=6.0,
        output_dir="out", cache_dir="c", geocode_cache="g.json",
    )
    settings = scrape.settings_for(options)
    assert settings.max_pages_per_state == 1
    assert settings.request_delay == 0.25
    assert settings.jobs == 9
    assert settings.max_retries == 1
    assert settings.scrape_details is False
    assert settings.geocode is False
    assert settings.include_contact is False
    assert settings.include_fees is False
    assert settings.refresh is True
    assert settings.max_drive_hours == 6.0
    assert (settings.cache_dir, settings.geocode_cache) == ("c", "g.json")


def test_retry_on_means_the_shipped_retry_count():
    assert scrape.settings_for(scrape.CrawlOptions(retry_failed=True)).max_retries == 3


def test_format_elapsed():
    assert scrape.format_elapsed(0) == "00:00:00"
    assert scrape.format_elapsed(767) == "00:12:47"
    assert scrape.format_elapsed(3_661) == "01:01:01"


def test_default_date_range_starts_today():
    start, end = scrape.default_date_range()
    assert start == date.today()
    assert (end - start).days == 365


# ---------------------------------------------------------------------------
# request counters
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, text="<html></html>"):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Stands in for requests.Session, counting what it was asked for."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.headers = {}

    def get(self, url, **kw):
        self.calls += 1
        return self.responses.pop(0) if self.responses else FakeResponse()


def make_fetcher(tmp_path, responses, **kw) -> Fetcher:
    fetcher = Fetcher(cache_dir=tmp_path / "cache", delay=0, **kw)
    fetcher.session = FakeSession(responses)
    return fetcher


def test_a_served_page_counts_one_request_and_no_failure(tmp_path):
    fetcher = make_fetcher(tmp_path, [FakeResponse(text="<p>hi</p>")])
    assert fetcher.get("https://example.test/a") == "<p>hi</p>"
    assert fetcher.stats() == {"requests": 1, "cache_hits": 0, "failures": 0}


def test_a_cached_page_counts_as_a_hit_not_a_request(tmp_path):
    fetcher = make_fetcher(tmp_path, [FakeResponse(text="<p>hi</p>")])
    fetcher.get("https://example.test/a")
    fetcher.get("https://example.test/a")
    stats = fetcher.stats()
    assert (stats["requests"], stats["cache_hits"]) == (1, 1)


def test_retries_off_gives_up_after_one_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    fetcher = make_fetcher(tmp_path, [FakeResponse(status_code=503)],
                           max_retries=1)
    with pytest.raises(Exception):
        fetcher.get("https://example.test/boom")
    assert fetcher.session.calls == 1
    assert fetcher.stats()["failures"] == 1


def test_retries_on_tries_again_before_counting_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    fetcher = make_fetcher(
        tmp_path,
        [FakeResponse(status_code=503), FakeResponse(text="<p>ok</p>")],
        max_retries=3,
    )
    assert fetcher.get("https://example.test/flaky") == "<p>ok</p>"
    assert fetcher.session.calls == 2
    assert fetcher.stats()["failures"] == 0


# ---------------------------------------------------------------------------
# cancelling, and the fields the rail can decline to keep
# ---------------------------------------------------------------------------

def test_a_cancelled_run_raises_instead_of_returning_half_a_crawl(tmp_path):
    settings = config.Settings(
        states=["Ohio"], cache_dir=str(tmp_path / "cache"),
        geocode_cache=str(tmp_path / "geo.json"),
    )
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(pipeline.Cancelled):
        pipeline.run(settings, cancel=cancel)


def test_run_hands_its_fetcher_back_so_counters_can_be_read_live(tmp_path):
    """The status bar's counters live on the Fetcher pipeline.run builds."""
    settings = config.Settings(
        states=["Ohio"], cache_dir=str(tmp_path / "cache"),
        geocode_cache=str(tmp_path / "geo.json"),
    )
    handed: list = []
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(pipeline.Cancelled):
        pipeline.run(settings, cancel=cancel, on_fetcher=handed.append)
    assert len(handed) == 1
    assert handed[0].stats() == {"requests": 0, "cache_hits": 0, "failures": 0}


def test_controller_counters_are_zero_before_a_crawl_starts():
    controller = scrape.ScrapeController(lambda kind, payload: None)
    assert controller.stats() == {"requests": 0, "cache_hits": 0, "failures": 0}


def test_controller_reports_the_counters_of_the_running_crawl(tmp_path):
    controller = scrape.ScrapeController(lambda kind, payload: None)
    fetcher = make_fetcher(tmp_path, [FakeResponse(text="<p>hi</p>")])
    controller._fetcher = fetcher
    fetcher.get("https://example.test/a")
    assert controller.stats()["requests"] == 1


def test_progress_carries_the_counters_the_status_bar_prints():
    progress = scrape.Progress(stage="crawl", done=2, total=10,
                               requests=4_892, failures=3)
    assert (progress.requests, progress.failures) == (4_892, 3)
    assert progress.fraction == 0.2


def test_progress_is_reported_with_a_stage_the_window_can_label():
    from fnscraper.gui.app import _STAGE_LABELS
    assert set(pipeline.STAGES) <= set(_STAGE_LABELS)


def test_windows_curses_is_not_requested_on_arm64():
    """It publishes no ARM64 wheel; asking fails the whole install.

    This is not hypothetical tidiness — it is what turned the Windows
    ARM64 build red, and it takes the CLI down with it, since pip aborts
    the entire requirements file on one unsatisfiable line.
    """
    markers = pytest.importorskip("packaging.markers")
    requirements = pytest.importorskip("packaging.requirements")

    text = (pathlib.Path(__file__).resolve().parent.parent
            / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    curses_line = next(ln for ln in lines if ln.startswith("windows-curses"))
    marker = requirements.Requirement(curses_line).marker
    assert marker is not None

    def wanted(platform_name: str, machine: str) -> bool:
        return marker.evaluate({"sys_platform": platform_name,
                                "platform_machine": machine})

    assert wanted("win32", "AMD64") is True
    assert wanted("win32", "ARM64") is False
    assert wanted("darwin", "arm64") is False
    assert wanted("linux", "x86_64") is False
    assert markers is not None


def test_declining_contact_details_clears_them():
    event = Event(event_id="e", name="n", url="u", contact_name="Pat",
                  contact_email="pat@example.test", contact_phone="555",
                  promoter_website="https://example.test")
    settings = config.Settings(include_contact=False)
    pipeline._strip_private_fields(event, settings)
    assert event.contact_name == "" and event.contact_email == ""
    assert event.contact_phone == "" and event.promoter_website == ""


def test_declining_fee_details_clears_them():
    event = Event(event_id="e", name="n", url="u", exhib_fee=250.0,
                  food_fee=400.0, booth_fee_text="$250")
    pipeline._strip_private_fields(event, config.Settings(include_fees=False))
    assert event.exhib_fee is None and event.food_fee is None
    assert event.booth_fee_text == ""


def test_keeping_both_leaves_the_event_untouched():
    event = Event(event_id="e", name="n", url="u", contact_name="Pat",
                  exhib_fee=250.0)
    pipeline._strip_private_fields(event, config.Settings())
    assert event.contact_name == "Pat" and event.exhib_fee == 250.0

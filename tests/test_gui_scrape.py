"""The desktop app's crawl plumbing: settings mapping, counters, cancelling."""

from __future__ import annotations

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


def test_progress_is_reported_with_a_stage_the_window_can_label():
    from fnscraper.gui.app import _STAGE_LABELS
    assert set(pipeline.STAGES) <= set(_STAGE_LABELS)


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

from datetime import date
from pathlib import Path

from fnscraper.models import Event
from fnscraper.parse import (
    listing_has_next_page,
    parse_detail_page,
    parse_event_url,
    parse_listing_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_event_url():
    assert parse_event_url(
        "https://festivalnet.com/77872/Cleveland-Ohio/Art-Shows/Walkabout"
    ) == ("77872", "Art-Shows")
    assert parse_event_url("https://festivalnet.com/craft-shows") is None


def test_listing_skips_ads_and_parses_fields():
    events = parse_listing_page(load("listing_sample.html"))
    assert [e.event_id for e in events] == ["77872", "12345"]

    walk = events[0]
    assert walk.name == "Sample Art Walk"
    assert walk.start_date == date(2026, 7, 10)
    assert walk.end_date == date(2026, 7, 10)
    assert walk.city == "Cleveland"
    assert walk.state == "OH"
    assert walk.venue == "The Treehouse"
    assert walk.category_slug == "Art-Shows"
    assert "artists and makers" in walk.description
    assert not walk.unconfirmed_date
    assert not walk.stale_listing

    fest = events[1]
    assert fest.name == "Salsa Fest"
    assert fest.category_slug == "Food-Festivals"
    assert fest.end_date == date(2026, 7, 19)
    assert fest.unconfirmed_date
    assert fest.stale_listing


def test_listing_next_page_detection():
    assert listing_has_next_page(load("listing_sample.html"), current_page=1)
    assert not listing_has_next_page(load("listing_sample.html"), current_page=2)
    assert not listing_has_next_page("<html><body>no pager</body></html>")


def test_detail_page_public_fields():
    ev = Event(event_id="77872", name="Sample", url="u", category_slug="Art-Shows")
    parse_detail_page(load("detail_sample.html"), ev)

    assert ev.start_date == date(2026, 7, 10)
    assert ev.end_date == date(2026, 7, 11)
    assert ev.hours_text == "Fri 5pm-9pm, Sat 10am-6pm"
    assert ev.admission == "free"
    assert ev.address == "820 College Avenue, Cleveland, OH 44113"
    assert ev.attendance == 2000
    assert ev.food_booths == 5
    assert ev.exhibitors == 20          # soft hyphen in label handled
    assert ev.juried == "yes"
    assert "until full" in ev.deadlines
    assert "Northcoast Promotions" in ev.promoter
    assert ev.exhib_fee is None         # anonymous page: no fee leaked


def test_detail_page_member_fees_and_na_fields():
    ev = Event(event_id="1", name="x", url="u")
    parse_detail_page(load("detail_member_sample.html"), ev)
    assert ev.attendance == 12000
    assert ev.exhibitors is None        # 'na' -> unknown
    assert ev.exhib_fee == 225.0
    assert ev.food_fee == 450.5
    assert ev.admission == "$5"

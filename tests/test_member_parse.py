"""Parsing the Pro-member detail layout.

FestivalNet serves logged-in users a completely different page from the
public one; these lock down the fields the booking plan depends on.
"""

from datetime import date
from pathlib import Path

import pytest

from fnscraper import parse
from fnscraper.models import Event

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pro_event() -> Event:
    html = (FIXTURES / "detail_pro_sample.html").read_text(encoding="utf-8")
    event = Event(event_id="1234", name="", url="https://festivalnet.com/1234/x/y/z")
    return parse.parse_detail_page(html, event)


def test_dispatches_to_the_member_parser():
    html = (FIXTURES / "detail_pro_sample.html").read_text(encoding="utf-8")
    assert parse.is_member_detail_page(html)
    public = (FIXTURES / "detail_sample.html").read_text(encoding="utf-8")
    assert not parse.is_member_detail_page(public)


def test_header_dates_venue_and_hours(pro_event: Event):
    assert pro_event.name == "Zanesville Harvest Festival"
    assert pro_event.start_date == date(2026, 9, 12)
    assert pro_event.end_date == date(2026, 9, 13)
    assert pro_event.hours_text == "Sat 10am-6pm; Sun 11am-5pm"
    assert pro_event.venue == "Riverside Park"
    assert pro_event.zip_code == "43701"


def test_crowd_and_fee_fields(pro_event: Event):
    assert pro_event.attendance == 12_000
    assert pro_event.exhibitors == 85
    assert pro_event.food_booths == 14
    assert pro_event.exhib_fee == 125.0
    assert pro_event.food_fee == 300.0
    assert pro_event.booth_fee_text == "$125"
    assert pro_event.admission == "free"


def test_deadlines_are_kept_per_track(pro_event: Event):
    assert pro_event.exhibit_deadline == "08/15/2026"
    assert pro_event.food_deadline == "until full"
    # The legacy free-text field stays populated for the TUI / picker.
    assert "08/15/2026" in pro_event.deadlines


def test_obfuscated_emails_are_decoded(pro_event: Event):
    # The exhibit director outranks the show director for a vendor booth.
    assert pro_event.contact_email == "booths@example-chamber.org"


def test_contact_falls_back_across_directors(pro_event: Event):
    assert pro_event.contact_name == "Dana Booth"
    # The exhibit director has no phone; it must not borrow the cell beside
    # it (which holds the email label).
    assert pro_event.contact_phone == "(740) 555-0101"


def test_promoter_excludes_the_quick_connect_popup(pro_event: Event):
    assert pro_event.promoter == "Example Chamber of Commerce"
    assert pro_event.promoter_website == "http://www.zanesvilleharvest.com"


def test_truncated_cells_are_restored_from_the_title_attribute(pro_event: Event):
    assert pro_event.application_info == "zanesvilleharvest.com/vendor-application"


def test_marks_the_record_as_pro_sourced(pro_event: Event):
    assert pro_event.pro_data is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("September 12 - 13, 2026", (date(2026, 9, 12), date(2026, 9, 13))),
        ("October 31 - November 2, 2026", (date(2026, 10, 31), date(2026, 11, 2))),
        ("July 4, 2026", (date(2026, 7, 4), date(2026, 7, 4))),
        ("no dates here", (None, None)),
    ],
)
def test_member_date_ranges(text, expected):
    assert parse._parse_member_dates(text) == expected


def test_deobfuscate_ignores_unrelated_scripts():
    html = "<script>var x = 1;</script>"
    assert parse.deobfuscate_emails(html) == html


def test_junk_addresses_are_not_treated_as_contacts():
    html = (
        '<table class="ProMembersSearchFullDetailsTable"><tbody>'
        '<tr><td><font class="font-color">Main Email:</font></td>'
        '<td><a href="mailto:foo@bar.com">foo@bar.com</a></td></tr>'
        "</tbody></table>"
    )
    event = parse.parse_member_detail_page(html, Event(event_id="1", name="", url=""))
    assert event.contact_email == ""


def test_header_dates_never_narrow_the_listings_range():
    """A cross-year header parses as one day; keep the listing's range."""
    html = (FIXTURES / "detail_pro_sample.html").read_text(encoding="utf-8")
    html = html.replace("September 12 - 13, 2026", "September 12, 2026")
    event = Event(
        event_id="1", name="", url="",
        start_date=date(2026, 9, 12), end_date=date(2026, 9, 20),
    )
    parse.parse_detail_page(html, event)
    assert event.start_date == date(2026, 9, 12)
    assert event.end_date == date(2026, 9, 20)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$125", 125.0),
        ("$50-$150", 150.0),       # budget the top of a range
        ("$600+", 600.0),
        ("$1,250", 1250.0),
        ("Contact", None),
        ("na", None),
        ("", None),
        ("$,", None),      # a lone comma is not a number
        ("$", None),
    ],
)
def test_fee_parsing(text, expected):
    assert parse._parse_fee(text) == expected

"""The results view's decisions, tested without a display attached."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from fnscraper.gui import viewmodel as vm
from fnscraper.gui.demo import sample_results
from fnscraper.models import Event, ScoreBreakdown, ScoredEvent

TODAY = date(2025, 6, 1)


def make_row(**kw) -> vm.Row:
    """One row, with only the fields a test cares about set."""
    event = Event(
        event_id=kw.pop("event_id", "e1"),
        name=kw.pop("name", "Test Festival"),
        url=kw.pop("url", "https://festivalnet.com/Craft-Shows/e1"),
        category_slug=kw.pop("category_slug", "Craft-Shows"),
        start_date=kw.pop("start_date", TODAY + timedelta(days=30)),
        end_date=kw.pop("end_date", TODAY + timedelta(days=31)),
        city=kw.pop("city", "Columbus"),
        state=kw.pop("state", "OH"),
        venue=kw.pop("venue", ""),
        promoter=kw.pop("promoter", ""),
        description=kw.pop("description", ""),
        attendance=kw.pop("attendance", 10_000),
    )
    breakdown = ScoreBreakdown(
        est_attendance=event.attendance or 0,
        booth_fee=kw.pop("booth_fee", 200.0),
        gross_revenue=kw.pop("gross_revenue", 2_000.0),
        total_cost=kw.pop("total_cost", 500.0),
        est_profit=kw.pop("est_profit", 900.0),
        score=kw.pop("score", 1_000.0),
    )
    assert not kw, f"unused kwargs: {sorted(kw)}"
    return vm.build_rows([ScoredEvent(event, breakdown)])[0]


def rows_for(specs: list[dict]) -> list[vm.Row]:
    scored = [make_row(**spec).scored for spec in specs]
    return vm.build_rows(scored)


# ---------------------------------------------------------------------------
# scores and formatting
# ---------------------------------------------------------------------------

def test_best_row_indexes_at_100_and_losses_at_zero():
    rows = rows_for([
        {"event_id": "a", "score": 5_000.0, "est_profit": 4_000.0},
        {"event_id": "b", "score": 500.0, "est_profit": 400.0},
        {"event_id": "c", "score": -300.0, "est_profit": -300.0},
    ])
    by_id = {r.key: r for r in rows}
    assert by_id["a"].get("overall") == 100.0
    assert 0 < by_id["b"].get("overall") < 100
    assert by_id["c"].get("overall") == 0.0
    assert by_id["c"].get("profit_index") == 0.0


def test_relative_index_is_monotonic():
    assert vm.relative_index(10, 100) < vm.relative_index(50, 100) \
        < vm.relative_index(100, 100)


def test_relative_index_handles_a_set_with_nothing_profitable():
    assert vm.relative_index(-5, 0) == 0.0


@pytest.mark.parametrize("kind,value,expected", [
    ("money", 1234.56, "$1,235"),
    ("money2", 1234.5, "$1,234.50"),
    ("int", 12345, "12,345"),
    ("score", 92.35, "92.3"),
    ("hours", 4.25, "4.2 h"),
    ("text", "", "—"),
    ("money", None, "—"),
    ("money", float("inf"), "—"),
])
def test_format_value(kind, value, expected):
    assert vm.format_value(kind, value) == expected


def test_compact_money_keeps_whole_dollars_until_billions():
    assert vm.compact_money(8_742_650) == "$8,742,650"
    assert vm.compact_money(2_500_000_000) == "$2.50B"


def test_compact_count_abbreviates_large_crowds():
    assert vm.compact_count(1_240_000) == "1.2M+"
    assert vm.compact_count(240_000) == "240K+"
    assert vm.compact_count(1_500) == "1,500"


def test_estimated_numbers_are_marked_with_a_tilde():
    scored = make_row().scored
    scored.breakdown.booth_fee_estimated = True
    scored.breakdown.attendance_estimated = True
    row = vm.build_rows([scored])[0]
    assert row.text("booth_fee").startswith("~$")
    assert row.text("attendance").startswith("~")


def test_a_real_fee_carries_no_tilde():
    scored = make_row().scored
    scored.breakdown.booth_fee_estimated = False
    row = vm.build_rows([scored])[0]
    assert row.text("booth_fee") == "$200"


def test_dates_render_without_platform_specific_format_codes():
    row = make_row(start_date=date(2025, 5, 15), end_date=date(2025, 5, 18))
    assert row.text("dates") == "May 15 - 18, 2025"
    row = make_row(start_date=date(2025, 5, 30), end_date=date(2025, 6, 2))
    assert row.text("dates") == "May 30 - Jun 2, 2025"
    row = make_row(start_date=date(2025, 5, 30), end_date=date(2025, 5, 30))
    assert row.text("dates") == "May 30, 2025"
    row = make_row(start_date=None, end_date=None)
    assert row.text("dates") == "—"


# ---------------------------------------------------------------------------
# filtering
# ---------------------------------------------------------------------------

def test_keyword_matches_name_city_and_description():
    rows = rows_for([
        {"event_id": "a", "name": "Salsa Fest"},
        {"event_id": "b", "name": "Quilt Show", "city": "Salsaville"},
        {"event_id": "c", "name": "Book Fair", "description": "hot salsa tasting"},
        {"event_id": "d", "name": "Kite Day"},
    ])
    kept = vm.Filters(keyword="salsa").apply(rows, TODAY)
    assert {r.key for r in kept} == {"a", "b", "c"}


def test_exact_match_requires_a_whole_word():
    rows = rows_for([
        {"event_id": "a", "name": "Art Fair"},
        {"event_id": "b", "name": "Smart Living Expo"},
    ])
    assert {r.key for r in vm.Filters(keyword="art").apply(rows, TODAY)} == {"a", "b"}
    exact = vm.Filters(keyword="art", exact_match=True).apply(rows, TODAY)
    assert {r.key for r in exact} == {"a"}


def test_location_filter_can_be_switched_off():
    rows = rows_for([{"event_id": "a", "city": "Toledo"},
                     {"event_id": "b", "city": "Dayton"}])
    on = vm.Filters(location="toledo").apply(rows, TODAY)
    assert [r.key for r in on] == ["a"]
    off = vm.Filters(location="toledo", use_location=False).apply(rows, TODAY)
    assert len(off) == 2


def test_state_filter_accepts_the_dropdown_label():
    rows = rows_for([{"event_id": "a", "state": "OH"},
                     {"event_id": "b", "state": "PA"}])
    kept = vm.Filters(state="Pennsylvania (PA)").apply(rows, TODAY)
    assert [r.key for r in kept] == ["b"]


def test_event_type_filter_uses_the_category_key():
    rows = rows_for([
        {"event_id": "a", "category_slug": "Craft-Shows"},
        {"event_id": "b", "category_slug": "Food-Festivals"},
    ])
    kept = vm.Filters(event_type="food").apply(rows, TODAY)
    assert [r.key for r in kept] == ["b"]


def test_date_range_keeps_an_event_that_overlaps_the_window():
    rows = rows_for([{
        "event_id": "a",
        "start_date": date(2025, 7, 28),
        "end_date": date(2025, 8, 3),
    }])
    inside = vm.Filters(date_from=date(2025, 8, 1),
                        date_to=date(2025, 8, 31)).apply(rows, TODAY)
    assert len(inside) == 1
    after = vm.Filters(date_from=date(2025, 9, 1),
                       date_to=date(2025, 9, 30)).apply(rows, TODAY)
    assert after == []


def test_dates_are_ignored_when_search_by_date_is_off():
    rows = rows_for([{"start_date": date(2030, 1, 1),
                      "end_date": date(2030, 1, 2)}])
    spec = vm.Filters(date_from=date(2025, 1, 1), date_to=date(2025, 2, 1),
                      use_dates=False)
    assert len(spec.apply(rows, TODAY)) == 1


def test_past_events_can_be_excluded():
    rows = rows_for([
        {"event_id": "old", "start_date": TODAY - timedelta(days=30),
         "end_date": TODAY - timedelta(days=29)},
        {"event_id": "new", "start_date": TODAY + timedelta(days=30),
         "end_date": TODAY + timedelta(days=31)},
    ])
    spec = vm.Filters(include_past=False, use_dates=False)
    assert [r.key for r in spec.apply(rows, TODAY)] == ["new"]


def test_attendance_bounds_are_inclusive():
    rows = rows_for([
        {"event_id": "small", "attendance": 1_000},
        {"event_id": "mid", "attendance": 5_000},
        {"event_id": "big", "attendance": 50_000},
    ])
    kept = vm.Filters(min_attendance=5_000, max_attendance=50_000).apply(rows, TODAY)
    assert {r.key for r in kept} == {"mid", "big"}


# ---------------------------------------------------------------------------
# sorting
# ---------------------------------------------------------------------------

def test_every_named_sort_order_is_implemented():
    rows = rows_for([
        {"event_id": "a", "name": "Zebra Fest", "score": 10.0,
         "est_profit": 10.0, "attendance": 100, "booth_fee": 900.0,
         "total_cost": 999.0, "start_date": TODAY + timedelta(days=90)},
        {"event_id": "b", "name": "Apple Fest", "score": 900.0,
         "est_profit": 800.0, "attendance": 90_000, "booth_fee": 50.0,
         "total_cost": 100.0, "start_date": TODAY + timedelta(days=5)},
    ])
    expected_first = {
        "best": "b", "profit": "b", "attendance": "b", "booth_fee": "b",
        "total_cost": "b", "date": "b", "deadline": "b", "name": "b",
    }
    for order, _label in vm.SORT_ORDERS:
        assert vm.sort_rows(rows, order)[0].key == expected_first[order], order


def test_sorting_is_stable_for_ties():
    rows = rows_for([
        {"event_id": "b", "name": "Beta", "score": 100.0},
        {"event_id": "a", "name": "Alpha", "score": 100.0},
    ])
    assert [r.key for r in vm.sort_rows(rows, "best")] == ["a", "b"]


def test_column_sort_puts_empty_cells_last_in_both_directions():
    rows = rows_for([
        {"event_id": "a", "venue": "Fairgrounds"},
        {"event_id": "b", "venue": ""},
        {"event_id": "c", "venue": "Armory"},
    ])
    ascending = vm.sort_by_column(rows, "venue", descending=False)
    assert [r.key for r in ascending] == ["c", "a", "b"]
    descending = vm.sort_by_column(rows, "venue", descending=True)
    assert [r.key for r in descending] == ["a", "c", "b"]


def test_numeric_column_sort_puts_missing_values_last():
    rows = rows_for([
        {"event_id": "a", "attendance": 10},
        {"event_id": "b", "attendance": None},
        {"event_id": "c", "attendance": 900},
    ])
    assert [r.key for r in vm.sort_by_column(rows, "attendance", True)] \
        == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# summary and pagination
# ---------------------------------------------------------------------------

def test_summary_counts_distinct_places_and_totals_money():
    rows = rows_for([
        {"event_id": "a", "city": "Columbus", "state": "OH",
         "booth_fee": 100.0, "gross_revenue": 1_000.0, "attendance": 5_000},
        {"event_id": "b", "city": "Columbus", "state": "OH",
         "booth_fee": 200.0, "gross_revenue": 2_000.0, "attendance": 6_000},
        {"event_id": "c", "city": "Erie", "state": "PA",
         "booth_fee": 300.0, "gross_revenue": 3_000.0, "attendance": 7_000},
    ])
    summary = vm.summarize(rows)
    assert (summary.count, summary.states, summary.cities) == (3, 2, 2)
    assert summary.total_booth_fee == 600.0
    assert summary.total_revenue == 6_000.0
    assert summary.total_attendance == 18_000


def test_summary_of_nothing_is_all_zeroes():
    assert vm.summarize([]) == vm.Summary()


def test_cards_cover_every_headline_number():
    cards = vm.cards_for(vm.summarize(rows_for([{}])))
    assert len(cards) == 6
    assert all(len(card) == 3 for card in cards)


@pytest.mark.parametrize("total,per_page,expected", [
    (0, 10, 1), (1, 10, 1), (10, 10, 1), (11, 10, 2), (236, 10, 24),
])
def test_page_count(total, per_page, expected):
    assert vm.page_count(total, per_page) == expected


def test_page_slice_clamps_out_of_range_pages():
    rows = rows_for([{"event_id": str(i)} for i in range(25)])
    assert len(vm.page_slice(rows, 3, 10)) == 5
    assert vm.page_slice(rows, 99, 10) == vm.page_slice(rows, 3, 10)
    assert vm.page_slice(rows, 0, 10) == vm.page_slice(rows, 1, 10)


def test_page_range_text():
    assert vm.page_range_text(236, 1, 10) == "Showing 1 to 10 of 236 festivals"
    assert vm.page_range_text(236, 24, 10) == "Showing 231 to 236 of 236 festivals"
    assert vm.page_range_text(0, 1, 10) == "No festivals to show"


def test_page_numbers_matches_the_first_page_layout():
    assert vm.page_numbers(1, 24) == [1, 2, 3, 4, 5, None, 24]


def test_page_numbers_brackets_the_current_page_in_the_middle():
    assert vm.page_numbers(12, 24) == [1, None, 10, 11, 12, 13, 14, None, 24]


def test_page_numbers_has_no_gaps_when_every_page_fits():
    assert vm.page_numbers(3, 6) == [1, 2, 3, 4, 5, 6]


def test_page_numbers_on_the_last_page():
    assert vm.page_numbers(24, 24) == [1, None, 20, 21, 22, 23, 24]


# ---------------------------------------------------------------------------
# columns
# ---------------------------------------------------------------------------

def test_default_columns_exist_and_lead_with_the_score():
    assert vm.DEFAULT_COLUMNS[0] == "overall"
    assert set(vm.DEFAULT_COLUMNS) <= set(vm.COLUMN_BY_KEY)


def test_every_column_renders_for_a_fully_populated_row():
    row = vm.build_rows(sample_results(TODAY))[0]
    for column in vm.COLUMN_BY_KEY:
        assert isinstance(row.text(column), str)


def test_unit_column_titles_follow_the_configured_product_noun():
    from fnscraper import config
    assert vm.column_title("cost_per_unit") == f"Cost / {config.UNIT_NAME}"


# ---------------------------------------------------------------------------
# the sample set the window opens with
# ---------------------------------------------------------------------------

def test_sample_results_are_scored_and_ordered():
    scored = sample_results(TODAY)
    assert len(scored) > 20
    scores = [s.breakdown.score for s in scored]
    assert scores == sorted(scores, reverse=True)
    assert all(s.event.start_date > TODAY for s in scored)
    assert all(s.event.drive_hours is not None for s in scored)

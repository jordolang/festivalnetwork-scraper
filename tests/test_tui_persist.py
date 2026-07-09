from datetime import date

from fnscraper import persist
from fnscraper.scoring import score_event
from fnscraper.tui import format_row, sort_for_picker
from tests.test_scoring import make_event


def scored(**kw):
    return score_event(make_event(**kw))


def test_cost_per_jar_computed():
    s = scored()
    b = s.breakdown
    assert b.jars_sold > 0
    assert abs(b.cost_per_jar - b.total_cost / b.jars_sold) < 1e-9


def test_sort_state_then_date_then_cost():
    rows = sort_for_picker([
        scored(event_id="1", state="PA", start_date=date(2026, 7, 11)),
        scored(event_id="2", state="OH", start_date=date(2026, 8, 1)),
        scored(event_id="3", state="OH", start_date=date(2026, 7, 11),
               distance_miles=400.0, drive_hours=6.9),   # pricier: lodging
        scored(event_id="4", state="OH", start_date=date(2026, 7, 11)),
    ])
    assert [r.event.event_id for r in rows] == ["4", "3", "2", "1"]


def test_format_row_shows_jar_cost_show_cost_location_date_name():
    s = scored()
    line = format_row(s, checked=True)
    assert line.startswith("[x] OH")
    assert "Jul 11" in line
    assert f"${s.breakdown.cost_per_jar:,.2f}" in line
    assert f"${s.breakdown.total_cost:,.0f}" in line
    assert "Test Fest — Columbus" in line
    assert "[ ]" in format_row(s, checked=False)


def test_format_row_shows_booth_fee_on_its_own():
    s = scored()
    b = s.breakdown
    assert b.booth_fee < b.total_cost          # booth is only part of the trip cost
    line = format_row(s, checked=False)
    # ~ prefix marks an estimated fee (no Pro login in the test fixture).
    assert b.booth_fee_estimated
    assert f"~${b.booth_fee:,.0f}" in line


def test_format_row_marks_real_booth_fee_without_tilde():
    s = scored()
    s.breakdown.booth_fee = 200.0
    s.breakdown.booth_fee_estimated = False
    line = format_row(s, checked=False)
    assert "$200" in line
    assert "~$200" not in line


def test_persist_roundtrip(tmp_path):
    original = [scored(), scored(event_id="2", attendance=None)]
    path = persist.save_results(original, tmp_path / "results.json")
    loaded = persist.load_results(path)
    assert len(loaded) == 2
    assert loaded[0].event.name == original[0].event.name
    assert loaded[0].event.start_date == original[0].event.start_date
    assert loaded[0].breakdown.cost_per_jar == original[0].breakdown.cost_per_jar
    assert loaded[1].breakdown.attendance_estimated

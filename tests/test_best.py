"""The weekend booking plan and its CSV export format."""

import csv
from datetime import date

import pytest

from fnscraper import best, config
from fnscraper.models import Event, ScoreBreakdown, ScoredEvent, open_weekdays

TODAY = date(2026, 7, 22)          # a Wednesday


def make(
    event_id="1",
    name="Test Show",
    start=date(2026, 8, 1),        # a Saturday
    end=None,
    score=1000.0,
    profit=900.0,
    hours="",
    deadlines="",
    **event_kwargs,
) -> ScoredEvent:
    event_kwargs.setdefault("city", "Columbus")
    event_kwargs.setdefault("state", "OH")
    event_kwargs.setdefault("drive_hours", 1.5)
    event = Event(
        event_id=event_id,
        name=name,
        url=f"https://festivalnet.com/{event_id}/City-Ohio/Craft-Shows/{event_id}",
        start_date=start,
        end_date=end or start,
        hours_text=hours,
        deadlines=deadlines,
        **event_kwargs,
    )
    breakdown = ScoreBreakdown(score=score, est_profit=profit)
    return ScoredEvent(event=event, breakdown=breakdown)


# ---------------------------------------------------------------------------
# Weekend maths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "day,anchor",
    [
        (date(2026, 8, 1), date(2026, 8, 1)),    # Sat -> itself
        (date(2026, 8, 2), date(2026, 8, 1)),    # Sun -> the Sat before
        (date(2026, 7, 31), date(2026, 8, 1)),   # Fri -> the Sat after
        (date(2026, 7, 29), date(2026, 8, 1)),   # Wed -> the Sat after
    ],
)
def test_saturday_of(day, anchor):
    assert best.saturday_of(day) == anchor


def test_add_months_clamps_to_the_end_of_the_month():
    assert best.add_months(date(2026, 7, 22), 3) == date(2026, 10, 22)
    assert best.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


@pytest.mark.parametrize(
    "hours,expected",
    [
        ("Thursdays 5 pm - 9 pm", {3}),
        ("Every Saturday noon-6pm", {5}),
        ("Sat 12pm-6pm; Sun 12pm-5pm", {5, 6}),
        ("Fri 5-11, Sat 10-11, Sun 12-6", {4, 5, 6}),
        ("Daily 10am-10pm", None),
        ("", None),
        ("Memorial Day thru Labor Day", None),
    ],
)
def test_open_weekdays(hours, expected):
    assert open_weekdays(hours) == expected


def test_weekly_series_only_claims_the_days_it_is_open():
    # Runs Jul 23 - Jul 30 on paper, but only on Thursdays.
    show = make(start=date(2026, 7, 23), end=date(2026, 7, 30),
                hours="Thursdays 5 pm - 9 pm")
    slots = best.weekend_slots(show.event)
    assert all(days == {3} for days in slots.values())


def test_a_monday_tuesday_only_show_gets_no_slot():
    show = make(start=date(2026, 8, 3), end=date(2026, 8, 4))   # Mon-Tue
    assert best.weekend_slots(show.event) == {}


def test_prime_days_outrank_midweek():
    assert best.weekend_multiplier({5, 6}) > best.weekend_multiplier({2, 3})


# ---------------------------------------------------------------------------
# Plan selection
# ---------------------------------------------------------------------------

def test_plan_takes_the_top_n_per_weekend():
    shows = [make(event_id=str(i), score=100.0 * i) for i in range(1, 9)]
    plan = best.build_plan(shows, months=3, top=5, today=TODAY)
    assert len(plan) == 5
    assert [s.scored.event.event_id for s in plan] == ["8", "7", "6", "5", "4"]


def test_plan_drops_unprofitable_shows():
    shows = [make(event_id="1", score=-50.0, profit=-50.0)]
    assert best.build_plan(shows, today=TODAY) == []


def test_plan_drops_missed_deadlines():
    shows = [make(event_id="1", deadlines="Art & Craft: 06/01/2026")]
    assert best.build_plan(shows, today=TODAY) == []


def test_plan_keeps_open_ended_deadlines():
    shows = [make(event_id="1", deadlines="Art & Craft: until full")]
    assert len(best.build_plan(shows, today=TODAY)) == 1


def test_plan_respects_the_horizon():
    inside = make(event_id="in", start=date(2026, 10, 17))
    outside = make(event_id="out", start=date(2026, 12, 5))
    plan = best.build_plan([inside, outside], months=3, today=TODAY)
    assert [s.scored.event.event_id for s in plan] == ["in"]


def test_a_recurring_show_cannot_fill_every_weekend():
    weekly = make(event_id="weekly", start=date(2026, 8, 1),
                  end=date(2026, 8, 29), hours="Every Saturday 9am-2pm")
    plan = best.build_plan([weekly], months=3, top=5, today=TODAY, max_repeats=2)
    assert len(plan) == 2


def test_midweek_show_only_wins_when_nothing_better_is_on():
    midweek = make(event_id="mid", start=date(2026, 7, 29), score=1000.0)  # Wed
    weekend = make(event_id="wknd", start=date(2026, 8, 1), score=900.0)   # Sat
    plan = best.build_plan([midweek, weekend], top=2, today=TODAY)
    same_weekend = [s for s in plan if s.weekend == date(2026, 8, 1)]
    assert [s.scored.event.event_id for s in same_weekend] == ["wknd", "mid"]


# ---------------------------------------------------------------------------
# Cell formatting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hours,expected",
    [(1.5, "1h 30m"), (0.25, "0h 15m"), (10.0, "10h 00m"), (None, "")],
)
def test_drive_time(hours, expected):
    assert best.drive_time(hours) == expected


def test_estimated_values_are_marked():
    s = make()
    s.breakdown.booth_fee = 150.0
    s.breakdown.booth_fee_estimated = True
    s.breakdown.est_attendance = 1500
    s.breakdown.attendance_estimated = True
    row = dict(zip(best.COLUMNS, best.row_for(s, TODAY)))
    assert row["Booth Fee"] == "$150.00*"
    assert row["Attendance"] == "1500*"


def test_real_fee_is_not_marked():
    s = make(exhib_fee=125.0, booth_fee_text="$125")
    s.breakdown.booth_fee = 125.0
    s.breakdown.booth_fee_estimated = False
    row = dict(zip(best.COLUMNS, best.row_for(s, TODAY)))
    assert row["Booth Fee"] == "$125.00"


def test_estimate_keeps_the_promoters_wording():
    s = make(booth_fee_text="Contact")
    s.breakdown.booth_fee = 275.0
    s.breakdown.booth_fee_estimated = True
    row = dict(zip(best.COLUMNS, best.row_for(s, TODAY)))
    assert row["Booth Fee"] == "$275.00* (Contact)"


@pytest.mark.parametrize(
    "deadlines,exhibit,expected",
    [
        ("", "08/15/2026", "08/15/2026"),
        ("Art & Craft: until full Music: 05/01/2026 Food: na", "", "until full"),
        ("Art & Craft: na Food: 09/01/2026", "", "09/01/2026"),
        ("Art & Craft: na Food: na", "", "Not listed"),
        ("", "", "Not listed"),
    ],
)
def test_application_deadline(deadlines, exhibit, expected):
    event = make(deadlines=deadlines, exhibit_deadline=exhibit).event
    assert best.application_deadline(event, TODAY) == expected


def test_address_is_one_mailing_line_from_either_layout():
    public = make(address="825 N. Jefferson Street, Milwaukee, WI 53202",
                  city="Milwaukee", state="WI").event
    assert best.address_cell(public) == "825 N. Jefferson Street, Milwaukee, WI 53202"

    pro = make(address="3340 Fairfield Road", city="Gettysburg",
               state="PA", zip_code="17325").event
    assert best.address_cell(pro) == "3340 Fairfield Road, Gettysburg, PA 17325"


def test_contact_name_falls_back_to_the_promoter():
    assert best.contact_name(make(promoter="Rotary Club").event) == "Rotary Club"
    assert best.contact_name(
        make(contact_name="Dana Booth", promoter="Rotary Club").event
    ) == "Dana Booth"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_stem_spans_the_days_the_plan_books():
    plan = best.build_plan(
        [make(event_id="a", start=date(2026, 8, 1)),
         make(event_id="b", start=date(2026, 9, 12))],
        today=TODAY,
    )
    assert best.export_stem(plan) == "export080126-091226"


def test_export_stem_ignores_a_long_tail_end_date():
    """A market running to New Year must not stamp the plan as six months."""
    plan = best.build_plan(
        [make(event_id="a", start=date(2026, 8, 1), end=date(2026, 12, 31),
              hours="Every Saturday 9am-2pm")],
        today=TODAY,
    )
    assert best.export_stem(plan) == "export080126-080826"


def test_slot_days_are_real_dates_in_the_weekend():
    show = make(event_id="a", start=date(2026, 7, 31), end=date(2026, 8, 2))
    plan = best.build_plan([show], today=TODAY)
    assert plan[0].days == [date(2026, 7, 31), date(2026, 8, 1), date(2026, 8, 2)]


def test_export_writes_a_readable_csv(tmp_path):
    plan = best.build_plan([make(event_id="a")], today=TODAY)
    csv_path = best.export_plan(plan, base_dir=tmp_path, today=TODAY)

    assert csv_path.parent.name == csv_path.stem
    assert (csv_path.parent / "SPEC.md").exists()

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == best.COLUMNS
    assert len(rows) == 2
    assert dict(zip(best.COLUMNS, rows[1]))["Event Name"] == "Test Show"


def test_every_row_has_one_cell_per_column():
    shows = [make(event_id=str(i)) for i in range(3)]
    plan = best.build_plan(shows, today=TODAY)
    for slot in plan:
        assert len(best.row_for(slot.scored, TODAY)) == len(best.COLUMNS)


def test_spec_documents_every_column():
    spec = best.spec_markdown()
    for column in best.COLUMNS:
        assert column in spec


def test_bookable_weekdays_exclude_monday_and_tuesday():
    assert config.BOOKABLE_WEEKDAYS == {2, 3, 4, 5, 6}
    assert config.PRIME_WEEKDAYS == {4, 5, 6}


def test_plan_drops_shows_that_are_already_over():
    over = make(event_id="over", start=date(2026, 7, 18), end=date(2026, 7, 19))
    assert best.build_plan([over], today=TODAY) == []


def test_the_current_weekend_survives_until_sunday_is_done():
    saturday = date(2026, 7, 25)
    show = make(event_id="1", start=saturday, end=date(2026, 7, 26))
    # Planning on the Sunday of that weekend must still offer it.
    plan = best.build_plan([show], today=date(2026, 7, 26))
    assert [s.weekend for s in plan] == [saturday]


def test_an_open_food_track_keeps_a_closed_craft_show_bookable():
    show = make(
        event_id="1",
        exhibit_deadline="06/01/2026",          # passed
        food_deadline="until full",             # still open
        deadlines="Art & Craft: 06/01/2026 Food: until full",
    )
    assert not best.deadline_passed(show.event, TODAY)
    assert len(best.build_plan([show], today=TODAY)) == 1


def test_every_track_closed_drops_the_show():
    show = make(
        event_id="1",
        exhibit_deadline="06/01/2026",
        food_deadline="06/15/2026",
        deadlines="Art & Craft: 06/01/2026 Food: 06/15/2026",
    )
    assert best.deadline_passed(show.event, TODAY)
    assert best.build_plan([show], today=TODAY) == []


@pytest.mark.parametrize(
    "hours,expected",
    [
        ("Fri-Sun 10am-8pm", {4, 5, 6}),
        ("Sat-Mon 10am-7pm", {5, 6, 0}),
        ("Wed thru Sun", {2, 3, 4, 5, 6}),
        ("Sat and Sun 9 am - 5 pm", {5, 6}),
        ("Fri 5-11, Sat 10-11, Sun 12-6", {4, 5, 6}),
    ],
)
def test_day_ranges_are_expanded(hours, expected):
    assert open_weekdays(hours) == expected


def test_a_friday_to_sunday_fair_keeps_its_saturday():
    show = make(start=date(2026, 7, 31), end=date(2026, 8, 2),
                hours="Fri-Sun 10am-8pm")
    assert best.weekend_slots(show.event) == {date(2026, 8, 1): {4, 5, 6}}


def test_export_ships_the_importer_contract(tmp_path):
    plan = best.build_plan([make(event_id="a")], today=TODAY)
    csv_path = best.export_plan(plan, base_dir=tmp_path, today=TODAY)
    contract = csv_path.parent / "IMPORT_FORMAT.md"
    assert contract.exists(), "the import spec must ship with every export"
    text = contract.read_text(encoding="utf-8")
    for column in best.COLUMNS:
        assert column in text
    # The header line in the doc must be the real one, not a stale copy.
    assert ",".join(best.COLUMNS) in text

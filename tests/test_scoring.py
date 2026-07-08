from datetime import date, timedelta

from fnscraper import config
from fnscraper.geocode import drive_estimate, haversine_miles
from fnscraper.models import Event
from fnscraper.pipeline import group_by_weekend
from fnscraper.scoring import score_event


def make_event(**kw) -> Event:
    base = dict(
        event_id="1", name="Test Fest", url="u", category_slug="Craft-Shows",
        start_date=date(2026, 7, 11), end_date=date(2026, 7, 11),
        city="Columbus", state="OH", attendance=5000, exhibitors=40,
        admission="free", distance_miles=55.0, drive_hours=0.95,
    )
    base.update(kw)
    return Event(**base)


def test_basic_score_positive_and_costs_add_up():
    s = score_event(make_event())
    b = s.breakdown
    assert b.est_profit > 0
    assert b.score > 0
    assert b.total_cost == b.booth_fee + b.fuel_cost + b.lodging_cost + b.meals_cost
    # A ~1 h day trip needs no hotel.
    assert b.lodging_cost == 0


def test_long_drive_adds_lodging_and_lowers_score():
    near = score_event(make_event())
    far = score_event(make_event(distance_miles=500.0, drive_hours=8.6))
    assert far.breakdown.lodging_cost > 0
    assert far.breakdown.total_cost > near.breakdown.total_cost
    assert far.breakdown.score < near.breakdown.score


def test_real_fee_overrides_estimate():
    est = score_event(make_event())
    real = score_event(make_event(exhib_fee=95.0))
    assert real.breakdown.booth_fee == 95.0
    assert not real.breakdown.booth_fee_estimated
    assert est.breakdown.booth_fee_estimated


def test_crowded_event_scores_below_roomy_event():
    roomy = score_event(make_event(exhibitors=25))
    crowded = score_event(make_event(exhibitors=250))
    assert crowded.breakdown.score < roomy.breakdown.score


def test_food_festival_beats_home_show():
    food = score_event(make_event(category_slug="Food-Festivals"))
    home = score_event(make_event(category_slug="Home-Garden-Shows"))
    assert food.breakdown.score > home.breakdown.score


def test_unknown_attendance_uses_default_with_note():
    s = score_event(make_event(attendance=None))
    assert s.breakdown.est_attendance == config.DEFAULT_ATTENDANCE
    assert s.breakdown.attendance_estimated
    assert any("undisclosed" in n for n in s.breakdown.notes)


def test_mega_event_sales_capped_by_throughput():
    s = score_event(make_event(attendance=700_000, exhibitors=400))
    assert s.breakdown.est_buyers <= config.MAX_DAILY_TRANSACTIONS
    assert any("throughput" in n for n in s.breakdown.notes)


def test_negative_profit_sinks():
    # Tiny event, brutal drive: costs swamp revenue.
    s = score_event(make_event(attendance=200, exhibitors=80,
                               distance_miles=600.0, drive_hours=9.9))
    assert s.breakdown.est_profit < 0
    assert s.breakdown.score < 0


def test_weekend_grouping():
    sat = score_event(make_event(start_date=date(2026, 7, 11)))
    fri = score_event(make_event(event_id="2", start_date=date(2026, 7, 10)))
    sun = score_event(make_event(event_id="3", start_date=date(2026, 7, 12)))
    next_wed = score_event(make_event(event_id="4", start_date=date(2026, 7, 15)))
    groups = group_by_weekend([sat, fri, sun, next_wed])
    assert set(groups) == {date(2026, 7, 11), date(2026, 7, 18)}
    assert len(groups[date(2026, 7, 11)]) == 3


def test_drive_estimate_matches_haversine_scaling():
    # Columbus is ~50 straight-line miles from Zanesville.
    straight = haversine_miles(config.HOME_LAT, config.HOME_LON, 39.9612, -82.9988)
    miles, hours = drive_estimate(39.9612, -82.9988)
    assert abs(miles - straight * config.ROAD_CIRCUITY) < 0.01
    assert hours < 1.5

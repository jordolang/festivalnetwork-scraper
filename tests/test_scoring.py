import pytest

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


# ---------------------------------------------------------------------------
# Sales economics: $10 jar, $25 average order, >= 1 sale per 40 attendees
# ---------------------------------------------------------------------------

def chip_revenue() -> float:
    """The chips riding along on an average order."""
    return config.CHIPS_ATTACH_RATE * config.CHIPS_PRICE


def chip_cogs() -> float:
    return config.CHIPS_ATTACH_RATE * config.CHIPS_COST


def test_price_points():
    assert config.JAR_PRICE == 10.0
    # The salsa half of the average order is the stated $25.
    assert config.avg_sale() - chip_revenue() == pytest.approx(25.0)


def test_the_average_order_is_the_three_for_25_deal():
    """$25 buys three jars, not two and a half."""
    assert config.jars_per_order() == 3.0
    assert config.cogs_per_order() - chip_cogs() == pytest.approx(
        3 * config.JAR_COST
    )


def test_every_deal_on_the_ladder_clears_its_cost():
    for jars, price in config.PRICE_LADDER:
        cogs = jars * config.jar_cost() + config.BUNDLE_EXTRA_COST.get(jars, 0.0)
        assert price > cogs, f"{jars} for ${price} loses money"


def test_the_ladder_gets_cheaper_per_jar_as_it_grows():
    per_jar = [price / jars for jars, price in config.PRICE_LADDER]
    assert per_jar == sorted(per_jar, reverse=True)


def test_avg_sale_constant_tracks_the_ladder():
    assert config.AVG_SALE == config.avg_sale()


def test_a_richer_order_mix_recomputes_everything(monkeypatch):
    monkeypatch.setattr(config, "ORDER_MIX", {1: 1.0, 12: 1.0})
    assert config.avg_sale() - chip_revenue() == pytest.approx((10.0 + 80.0) / 2)
    assert config.jars_per_order() == pytest.approx((1 + 12) / 2)


def test_bundled_chips_are_costed(monkeypatch):
    monkeypatch.setattr(config, "ORDER_MIX", {5: 1.0})
    expected = 5 * config.jar_cost() + config.BUNDLE_EXTRA_COST[5]
    assert config.cogs_per_order() - chip_cogs() == pytest.approx(expected)


def test_an_order_mix_off_the_ladder_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "ORDER_MIX", {7: 1.0})
    with pytest.raises(KeyError):
        config.avg_sale()


def test_conversion_is_one_in_forty_at_baseline():
    # 27 booths against 4,000 people is right at the ideal ratio, and an
    # unstated admission is neutral, so nothing moves the 1-in-40 baseline.
    b = score_event(
        make_event(attendance=4_000, exhibitors=27, admission="")
    ).breakdown
    assert b.est_buyers == pytest.approx(4_000 / 40, rel=0.02)


def test_free_admission_beats_the_baseline():
    free = score_event(make_event(attendance=4_000, exhibitors=27)).breakdown
    neutral = score_event(
        make_event(attendance=4_000, exhibitors=27, admission="")
    ).breakdown
    assert free.est_buyers > neutral.est_buyers


def test_conversion_never_drops_below_one_in_forty():
    # Bad category fit and a crowded field would otherwise drag it under.
    b = score_event(
        make_event(attendance=4_000, exhibitors=400,
                   category_slug="Home-Garden-Shows")
    ).breakdown
    assert b.est_buyers >= 4_000 * config.MIN_CAPTURE_RATE
    assert any("1 sale per 40" in n for n in b.notes)


def test_a_good_fit_beats_the_floor():
    b = score_event(
        make_event(attendance=4_000, exhibitors=15,
                   category_slug="Food-Festivals")
    ).breakdown
    assert b.est_buyers > 4_000 * config.MIN_CAPTURE_RATE


def test_revenue_follows_the_average_order():
    b = score_event(make_event(attendance=4_000, exhibitors=27)).breakdown
    assert b.gross_revenue == pytest.approx(b.est_buyers * config.avg_sale())


def test_jars_sold_follows_the_deal_not_the_single_jar_price():
    b = score_event(make_event()).breakdown
    # Three jars per $25 order — NOT revenue / $10, which would say 2.5.
    assert b.jars_sold == pytest.approx(b.est_buyers * 3.0)
    assert b.jars_sold > b.gross_revenue / config.JAR_PRICE


# ---------------------------------------------------------------------------
# One bookable occurrence, not a whole season
# ---------------------------------------------------------------------------

def test_a_multi_day_fair_is_costed_across_all_its_days():
    fair = make_event(start_date=date(2026, 8, 1), end_date=date(2026, 8, 10))
    assert fair.occurrence_days() == 10
    assert fair.schedule_source() == "continuous"


def test_a_long_run_with_no_published_hours_defaults_to_the_weekend():
    """Nothing says which days; a month-long listing is not 30 days of work."""
    run = make_event(start_date=date(2026, 8, 1), end_date=date(2026, 8, 30),
                     hours_text="", description="A grand time for all.")
    assert run.schedule_source() == "assumed"
    assert run.occurrence_days() == 3                  # Fri-Sun
    assert any("confirm the dates" in n
               for n in score_event(run).breakdown.notes)


def test_recurrence_is_read_from_the_name_when_hours_are_missing():
    run = make_event(name="Main Street Fridays - August",
                     start_date=date(2026, 8, 7), end_date=date(2026, 8, 28),
                     hours_text="")
    assert run.schedule_source() == "text"
    assert run.occurrence_days() == 1


def test_recurrence_is_read_from_the_description():
    run = make_event(
        name="Bristol Renaissance Faire",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 30), hours_text="",
        description="For 9 glorious weekends, each Saturday and Sunday, "
                    "visitors romp through Elizabethan England.",
    )
    assert run.occurrence_days() == 2


def test_a_closed_clause_does_not_open_those_days():
    run = make_event(
        start_date=date(2026, 8, 22), end_date=date(2026, 9, 27),
        hours_text="Sat 10:30am-6:30pm; Sun 10:30am-; Mon-Fri closed",
    )
    assert run.open_weekdays() == {5, 6}
    assert run.occurrence_days() == 2


def test_a_weekend_market_is_costed_as_one_weekend():
    """A Sat/Sun market listed across a month is a 2-day booking."""
    market = make_event(
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 30),
        hours_text="Sat and Sun 9 am - 5 pm",
        distance_miles=420.0, drive_hours=7.3,      # far enough to need a hotel
    )
    assert market.occurrence_days() == 2

    b = score_event(market).breakdown
    # Two nights away, not thirty.
    assert b.lodging_cost == 2 * config.LODGING_PER_NIGHT
    assert b.est_buyers <= 2 * config.MAX_DAILY_TRANSACTIONS


def test_a_weekly_market_does_not_outrank_a_real_fair_on_span_alone():
    market = score_event(make_event(
        event_id="market", attendance=500_000, exhibitors=400,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 30),
        hours_text="Sat and Sun 9 am - 5 pm",
        distance_miles=420.0, drive_hours=7.3,
    ))
    fair = score_event(make_event(
        event_id="fair", attendance=50_000, exhibitors=120,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 3),
    ))
    # The nearby fair wins on cost-efficiency once the market is costed
    # as the two-day booking it really is.
    assert fair.breakdown.score > market.breakdown.score


def test_a_single_weekday_series_is_one_day():
    series = make_event(
        start_date=date(2026, 7, 23), end_date=date(2026, 7, 30),
        hours_text="Thursdays 5 pm - 9 pm",
    )
    assert series.occurrence_days() == 1


def test_cogs_is_priced_per_jar_not_as_a_slice_of_revenue():
    b = score_event(make_event()).breakdown
    salsa_cogs = b.cogs - b.est_buyers * chip_cogs()
    assert salsa_cogs == pytest.approx(b.jars_sold * config.JAR_COST)
    assert config.JAR_COST == 3.50


def test_package_pricing_costs_more_goods_than_single_jars_would():
    """The package discount is real margin, and the model must feel it."""
    b = score_event(make_event()).breakdown
    salsa_revenue = b.gross_revenue - b.est_buyers * chip_revenue()
    salsa_cogs = b.cogs - b.est_buyers * chip_cogs()
    naive_cogs = (salsa_revenue / config.JAR_PRICE) * config.JAR_COST
    assert salsa_cogs > naive_cogs
    assert salsa_cogs == pytest.approx(naive_cogs * 1.2)  # 3 jars vs 2.5


def test_repricing_a_deal_moves_revenue_but_not_the_goods(monkeypatch):
    """Charging more for the same 3-jar deal does not consume more salsa."""
    base = score_event(make_event()).breakdown
    monkeypatch.setattr(config, "PRICE_LADDER",
                        [(1, 10.0), (3, 28.0), (4, 32.0), (5, 40.0), (12, 80.0)])
    dearer = score_event(make_event()).breakdown
    assert dearer.gross_revenue > base.gross_revenue
    assert dearer.jars_sold == pytest.approx(base.jars_sold)
    assert dearer.cogs == pytest.approx(base.cogs)


def test_batch_yield_derives_the_jar_cost(monkeypatch):
    monkeypatch.setattr(config, "BATCH_JARS", 1_000)
    assert config.jar_cost() == pytest.approx(2.50)
    monkeypatch.setattr(config, "BATCH_JARS", None)
    assert config.jar_cost() == pytest.approx(3.50)


def test_the_quoted_cost_band_brackets_the_batch_maths():
    low, high = config.JAR_COST_RANGE
    batch = config.BATCH_INGREDIENT_COST + config.BATCH_PACKAGING_COST
    # $2,500 a batch implies 715 jars at the top of the band, 1,000 at the
    # bottom — both plausible yields, which is why the band is what it is.
    assert 700 <= batch / high <= 720
    assert batch / low == pytest.approx(1_000)


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------

def test_chips_are_the_best_margin_item_at_the_booth():
    chips = (config.CHIPS_PRICE - config.CHIPS_COST) / config.CHIPS_PRICE
    best_salsa = max(
        (price - jars * config.jar_cost()) / price
        for jars, price in config.PRICE_LADDER
    )
    assert chips > best_salsa


def test_the_five_jar_deal_gives_the_chips_away():
    """It costs a bag and forgoes the $3.00 it would have fetched."""
    assert config.BUNDLE_EXTRA_COST[5] == config.CHIPS_COST
    five = dict((j, p) for j, p in config.PRICE_LADDER)[5]
    four = dict((j, p) for j, p in config.PRICE_LADDER)[4]
    # Five jars are charged at the 4-jar rate; the chips ride along free.
    assert five == pytest.approx(four / 4 * 5)


def test_one_order_in_eight_takes_chips():
    assert config.CHIPS_ATTACH_RATE == 0.125
    # The $25 figure is the salsa deal; the average *order* is a shade more.
    assert config.avg_sale() == pytest.approx(25.0 + 0.125 * 3.00)
    assert config.cogs_per_order() == pytest.approx(3 * 3.50 + 0.125 * 1.00)
    assert config.jars_per_order() == 3.0     # chips are not salsa


def test_an_attach_rate_adds_revenue_and_cost(monkeypatch):
    monkeypatch.setattr(config, "CHIPS_ATTACH_RATE", 0.25)
    assert config.avg_sale() == pytest.approx(25.0 + 0.25 * 3.00)
    assert config.cogs_per_order() == pytest.approx(3 * 3.50 + 0.25 * 1.00)
    # Jars are unaffected — chips are not salsa.
    assert config.jars_per_order() == 3.0


def test_attached_chips_raise_profit(monkeypatch):
    base = score_event(make_event()).breakdown
    monkeypatch.setattr(config, "CHIPS_ATTACH_RATE", 0.25)
    withchips = score_event(make_event()).breakdown
    assert withchips.est_profit > base.est_profit
    gain = withchips.est_profit - base.est_profit
    lift = 0.25 - 0.125
    assert gain == pytest.approx(base.est_buyers * lift * 2.00)


def test_chips_never_touch_the_jar_count(monkeypatch):
    base = score_event(make_event()).breakdown
    monkeypatch.setattr(config, "CHIPS_ATTACH_RATE", 0.75)
    heavy = score_event(make_event()).breakdown
    assert heavy.jars_sold == pytest.approx(base.jars_sold)

"""Profitability-per-dollar scoring for a traveling salsa vendor.

The model estimates, for each event:

    revenue  = buyers x average sale
    buyers   = capture(attendance) x category fit x admission factor
               x competition factor x data-quality factor
    cost     = booth fee + fuel + lodging + meals          (out of pocket)
    profit   = revenue - cost of goods - cost
    ROI      = profit / cost

The final ranking score is ``profit x sqrt(ROI)`` — it rewards absolute
profit but tilts hard toward events that return the most per dollar risked,
which is exactly "most profitable for the lowest cost out of pocket."
Negative-profit events score negative and sink to the bottom.
"""

from __future__ import annotations

import math

from . import config
from .models import Event, ScoreBreakdown, ScoredEvent


def _category_fit(category_slug: str) -> float:
    slug = category_slug.lower()
    for key, fit in config.CATEGORY_FIT.items():
        if key in slug:
            return fit
    return config.CATEGORY_FIT["other"]


def _booth_fee(event: Event, attendance: int) -> tuple[float, bool]:
    """Real fee when available (Pro login), else attendance-tier estimate."""
    if event.exhib_fee is not None:
        return event.exhib_fee, False
    for cap, fee in config.FEE_TIERS:
        if attendance <= cap:
            base = fee
            break
    else:  # pragma: no cover - FEE_TIERS ends with inf
        base = config.FEE_TIERS[-1][1]
    if event.food_booths:
        base *= config.FOOD_FEE_MULTIPLIER
    return base, True


def _event_days(event: Event) -> int:
    if event.start_date and event.end_date and event.end_date >= event.start_date:
        return (event.end_date - event.start_date).days + 1
    return 1


def score_event(event: Event) -> ScoredEvent:
    b = ScoreBreakdown()

    # -- inputs, with estimates flagged --------------------------------
    if event.attendance:
        b.est_attendance = event.attendance
    else:
        b.est_attendance = config.DEFAULT_ATTENDANCE
        b.attendance_estimated = True
        b.notes.append("attendance undisclosed; assumed "
                       f"{config.DEFAULT_ATTENDANCE:,}")

    if event.exhibitors:
        b.est_exhibitors = event.exhibitors
    else:
        b.est_exhibitors = config.DEFAULT_EXHIBITORS
        b.exhibitors_estimated = True

    days = _event_days(event)

    # -- demand-side multipliers ---------------------------------------
    b.category_fit = _category_fit(event.category_slug)

    attendees_per_exhibitor = b.est_attendance / max(b.est_exhibitors, 1)
    # 1.0 at the ideal ratio, shrinking as booths crowd the same crowd,
    # capped so a tiny show with 3 booths doesn't look artificially golden.
    b.competition_factor = min(
        1.25,
        math.sqrt(attendees_per_exhibitor / config.IDEAL_ATTENDEES_PER_EXHIBITOR),
    )
    if attendees_per_exhibitor < 60:
        b.notes.append("crowded: "
                       f"{attendees_per_exhibitor:.0f} attendees/booth")

    admission = (event.admission or "").lower()
    if "free" in admission:
        b.admission_factor = config.ADMISSION_FREE_BONUS
    elif admission and admission not in ("na", "unknown", "undisclosed"):
        b.admission_factor = config.ADMISSION_PAID_PENALTY
    else:
        b.admission_factor = 1.0

    b.quality_factor = 1.0
    if event.unconfirmed_date:
        b.quality_factor *= config.UNCONFIRMED_DATE_PENALTY
        b.notes.append("date unconfirmed by promoter")
    if event.stale_listing:
        b.quality_factor *= config.STALE_LISTING_PENALTY
        b.notes.append("listing not recently updated")

    # -- revenue ---------------------------------------------------------
    base_buyers = config.CAPTURE_RATE * (b.est_attendance ** config.CAPTURE_EXPONENT)
    b.est_buyers = (
        base_buyers
        * b.category_fit
        * b.competition_factor
        * b.admission_factor
        * b.quality_factor
    )
    throughput_cap = config.MAX_DAILY_TRANSACTIONS * days
    if b.est_buyers > throughput_cap:
        b.est_buyers = throughput_cap
        b.notes.append(
            f"sales capped at booth throughput ({config.MAX_DAILY_TRANSACTIONS}/day)"
        )
    b.gross_revenue = b.est_buyers * config.AVG_SALE
    b.cogs = b.gross_revenue * config.UNIT_COST_RATIO

    # -- out-of-pocket cost ----------------------------------------------
    b.booth_fee, b.booth_fee_estimated = _booth_fee(event, b.est_attendance)

    miles = event.distance_miles or 0.0
    hours = event.drive_hours or 0.0
    b.fuel_cost = (miles * 2) / config.MPG * config.GAS_PRICE

    nights = 0
    if hours > config.MAX_DAYTRIP_HOURS:
        # Sleep there the night before each show day; drive home after.
        nights = days
    b.lodging_cost = nights * config.LODGING_PER_NIGHT
    trip_days = days + (1 if hours > config.MAX_DAYTRIP_HOURS else 0)
    b.meals_cost = trip_days * config.MEALS_PER_DAY

    b.total_cost = b.booth_fee + b.fuel_cost + b.lodging_cost + b.meals_cost

    # -- profit & score ----------------------------------------------------
    b.est_profit = b.gross_revenue - b.cogs - b.total_cost
    b.roi = b.est_profit / b.total_cost if b.total_cost > 0 else 0.0

    if b.est_profit <= 0 or b.roi <= 0:
        b.score = b.est_profit          # negative: sinks to the bottom
    else:
        b.score = b.est_profit * math.sqrt(b.roi)

    return ScoredEvent(event=event, breakdown=b)

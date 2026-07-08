"""Data structures shared across the scraper."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Event:
    # Identity
    event_id: str
    name: str
    url: str
    category_slug: str = ""          # e.g. "Art-Shows" from the URL

    # When
    start_date: date | None = None
    end_date: date | None = None
    hours_text: str = ""

    # Where
    city: str = ""
    state: str = ""
    venue: str = ""
    address: str = ""
    lat: float | None = None
    lon: float | None = None

    # Public detail fields
    admission: str = ""
    attendance: int | None = None
    exhibitors: int | None = None
    food_booths: int | None = None
    juried: str = ""
    deadlines: str = ""
    promoter: str = ""
    description: str = ""

    # Member-only fields (populated only when logged in)
    exhib_fee: float | None = None
    food_fee: float | None = None

    # Data-quality flags
    unconfirmed_date: bool = False
    stale_listing: bool = False

    # Derived (filled by geocode/scoring)
    distance_miles: float | None = None
    drive_hours: float | None = None


@dataclass
class ScoreBreakdown:
    est_attendance: int = 0
    attendance_estimated: bool = False
    est_exhibitors: int = 0
    exhibitors_estimated: bool = False
    category_fit: float = 1.0
    competition_factor: float = 1.0
    admission_factor: float = 1.0
    quality_factor: float = 1.0

    est_buyers: float = 0.0
    gross_revenue: float = 0.0
    cogs: float = 0.0

    booth_fee: float = 0.0
    booth_fee_estimated: bool = True
    fuel_cost: float = 0.0
    lodging_cost: float = 0.0
    meals_cost: float = 0.0
    total_cost: float = 0.0

    est_profit: float = 0.0
    roi: float = 0.0                 # profit per out-of-pocket dollar
    score: float = 0.0               # final ranking score

    notes: list[str] = field(default_factory=list)


@dataclass
class ScoredEvent:
    event: Event
    breakdown: ScoreBreakdown

    @property
    def weekend_key(self) -> date | None:
        """The Saturday of the weekend this event belongs to."""
        d = self.event.start_date
        if d is None:
            return None
        # Weekday: Mon=0..Sun=6.  Map each date to its week's Saturday.
        offset = (5 - d.weekday()) % 7
        if d.weekday() == 6:                     # Sunday belongs to prior Saturday
            offset = -1
        from datetime import timedelta
        return d + timedelta(days=offset)

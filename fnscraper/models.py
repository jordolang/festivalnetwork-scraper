"""Data structures shared across the scraper."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

# Day names as they appear in FestivalNet hours strings.
_DAY_WORDS = [
    (r"mon", 0), (r"tues?", 1), (r"wed(?:nes)?", 2), (r"thu(?:r?s?)", 3),
    (r"fri", 4), (r"sat(?:ur)?", 5), (r"sun", 6),
]
_DAY_RE = re.compile(
    r"\b(?:" + "|".join(f"(?P<d{n}>{pat})" for pat, n in _DAY_WORDS)
    + r")(?:day)?s?\b",
    re.I,
)
# What can sit between two day names to make them a range ("Fri-Sun").
_RANGE_SEP_RE = re.compile(r"^\s*(?:-|–|—|to|thru|through)\s*$", re.I)
# A clause saying a day is *shut* ("Mon-Fri closed") must not open it.
_CLOSED_RE = re.compile(r"\bclosed?\b", re.I)
# "open weekends" with no day names at all.
_WEEKEND_RE = re.compile(r"\bweek\s?ends?\b", re.I)

# A listing running at least this long is treated as a series rather than
# one continuous engagement when nothing says otherwise.  Set above the
# length of a normal multi-day county fair so those stay continuous.
LONG_RUN_DAYS = 15
# What a long run defaults to when neither the hours, the name, nor the
# description say which days it is open.
ASSUMED_LONG_RUN_WEEKDAYS = frozenset({4, 5, 6})     # Fri-Sun


def _days_in_clause(text: str) -> set[int]:
    """Every weekday named in one clause, expanding ranges."""
    hits: list[tuple[int, int, int]] = []
    for match in _DAY_RE.finditer(text):
        for name, value in match.groupdict().items():
            if value:
                hits.append((int(name[1:]), match.start(), match.end()))
                break

    days: set[int] = set()
    i = 0
    while i < len(hits):
        day, _, end = hits[i]
        days.add(day)
        if i + 1 < len(hits):
            next_day, next_start, _ = hits[i + 1]
            if _RANGE_SEP_RE.match(text[end:next_start]):
                cursor = day
                while cursor != next_day:
                    cursor = (cursor + 1) % 7
                    days.add(cursor)
                i += 1                    # the range's far end is consumed
        i += 1
    return days


def open_weekdays(hours_text: str) -> set[int] | None:
    """Days named in an hours string (Mon=0..Sun=6), or None if it names none.

    A listing like "Jazz in the Park" spans 07/23-07/30 but its hours read
    "Thursdays 5 pm - 9 pm" — it is open one weekday, not eight.  Ranges are
    expanded, so "Fri-Sun" covers all three days and not just the endpoints.

    Clauses are read independently so that a closure ("Sat 10:30am-6:30pm;
    Sun 10:30am-; Mon-Fri closed") subtracts its days instead of opening
    them — read naively that string says the show runs all week.
    """
    text = hours_text or ""
    opened: set[int] = set()
    closed: set[int] = set()
    for clause in re.split(r"[;,]", text):
        days = _days_in_clause(clause)
        if not days:
            continue
        if _CLOSED_RE.search(clause):
            closed |= days
        else:
            opened |= days

    days = opened - closed
    if days:
        return days
    if _WEEKEND_RE.search(text):
        return {5, 6}
    return None


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
    zip_code: str = ""
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

    # Member-only fields (populated only when logged in as a Pro member).
    # FestivalNet serves logged-in users an entirely different page layout;
    # see parse.parse_member_detail_page.
    exhib_fee: float | None = None
    food_fee: float | None = None
    booth_fee_text: str = ""         # raw fee string: "$50", "$600+", "Contact"
    exhibit_deadline: str = ""       # application deadline, exhibit booths
    food_deadline: str = ""          # application deadline, food booths
    application_info: str = ""       # "How/Where apply" — how to get the form
    contact_name: str = ""           # show/exhibit director
    contact_email: str = ""
    contact_phone: str = ""
    promoter_website: str = ""
    pro_data: bool = False           # True when parsed from a Pro-member page

    # Data-quality flags
    unconfirmed_date: bool = False
    stale_listing: bool = False

    # Derived (filled by geocode/scoring)
    distance_miles: float | None = None
    drive_hours: float | None = None

    def running_dates(self, cap_days: int = 21) -> list[date]:
        """Every calendar day the show is open.

        ``cap_days`` guards against listings whose end date is a typo (or a
        months-long "market runs all summer" entry) from expanding into a
        huge list.
        """
        if self.start_date is None:
            return []
        end = self.end_date or self.start_date
        if end < self.start_date:
            end = self.start_date
        span = min((end - self.start_date).days, cap_days - 1)
        return [self.start_date + timedelta(days=i) for i in range(span + 1)]

    def weekdays(self) -> set[int]:
        """Weekday numbers the show runs on (Mon=0 .. Sun=6)."""
        return {d.weekday() for d in self.running_dates()}

    def _schedule(self) -> tuple[set[int] | None, str]:
        """(days the show is open, where we learned it).

        Most long listings publish no hours at all, and reading that as
        "open every day for a month" is how a weekend market ends up costed
        as a 30-day engagement.  The cadence is usually stated somewhere
        else — "Main Street **Fridays**", "Fall Foliage **Weekends**", "each
        Saturday and Sunday" in the blurb — so fall back to those, and
        failing that assume a long run is a Fri-Sun series.  The fallback is
        gated on length: an incidental "Friday set-up" in the description of
        a two-day show must not restrict it.
        """
        named = open_weekdays(self.hours_text)
        if named:
            return named, "hours"
        if len(self.running_dates()) < LONG_RUN_DAYS:
            return None, "continuous"
        named = open_weekdays(f"{self.name}. {self.description}")
        if named:
            return named, "text"
        return set(ASSUMED_LONG_RUN_WEEKDAYS), "assumed"

    def open_weekdays(self) -> set[int] | None:
        """Days the show is open, or None when it runs straight through."""
        return self._schedule()[0]

    def schedule_source(self) -> str:
        """'hours' | 'text' | 'assumed' | 'continuous' — see _schedule."""
        return self._schedule()[1]

    def open_dates(self) -> list[date]:
        """Calendar days the show is actually open for business."""
        days = self.running_dates()
        named = self.open_weekdays()
        if named is None:
            return days
        return [d for d in days if d.weekday() in named]

    def occurrence_days(self) -> int:
        """Days in one *bookable* run of this show.

        A ten-day county fair is one ten-day engagement.  A flea market
        listed as "08/01 - 08/30, Sat and Sun" is not a 30-day engagement —
        it is a two-day booking you could repeat.  Costing the latter as a
        month means 30 hotel nights and a 4,500-sale ceiling against a
        single booth fee, which floats recurring markets to the top of every
        weekend.  A listing that names its days *and* runs over a week is
        the recurring kind; score one week's worth of it.
        """
        days = self.open_dates()
        if not days:
            return 1
        recurring = (
            self.open_weekdays() is not None
            and (days[-1] - days[0]).days >= 7
        )
        if not recurring:
            return len(days)
        # Group by the Saturday that leads each weekend, so a Sat/Sun/Mon
        # run counts as one outing rather than splitting across two weeks.
        per_week = Counter(
            d - timedelta(days=(d.weekday() - 5) % 7) for d in days
        )
        return max(per_week.values())


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

    jars_sold: float = 0.0           # estimated jars moved at the show
    cost_per_jar: float = 0.0        # out-of-pocket cost to sell one jar

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

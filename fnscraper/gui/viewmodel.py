"""Everything the results view does that is not drawing.

Columns, formatting, filtering, sorting, pagination and the headline
numbers all live here as plain functions over plain data, so they can be
tested without a display attached.  :mod:`fnscraper.gui.app` should read
like window assembly; the decisions are here.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterable, Sequence

from .. import categories, config
from ..models import ScoredEvent
from ..tui import deadline_date

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

# kind drives both alignment defaults and formatting:
#   text  plain string          int    thousands-separated integer
#   money whole dollars         money2 dollars and cents
#   score 0-100 index, green    hours  "4.2 h"
KINDS = ("text", "int", "money", "money2", "score", "hours")


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    width: int
    kind: str = "text"
    anchor: str = "w"
    default: bool = False
    # Sorting a column of "n/a" cells has to put them somewhere; missing
    # values sort last whichever way the arrow points.
    numeric: bool = False


def _col(key, title, width, kind="text", anchor=None, default=False) -> Column:
    numeric = kind in ("int", "money", "money2", "score", "hours")
    if anchor is None:
        anchor = "e" if numeric else "w"
    return Column(key, title, width, kind, anchor, default, numeric)


COLUMNS: tuple[Column, ...] = (
    _col("overall", "Overall Score", 92, "score", "center", True),
    _col("name", "Festival Name", 250, "text", "w", True),
    _col("city", "City", 118, "text", "w", True),
    _col("state", "State", 62, "text", "w", True),
    _col("dates", "Dates", 146, "text", "w", True),
    _col("attendance", "Attendance", 98, "int", None, True),
    _col("booth_fee", "Booth Fee (USD)", 112, "money", None, True),
    _col("gross_revenue", "Est. Revenue (USD)", 126, "money", None, True),
    _col("est_profit", "Est. Profit (USD)", 118, "money", None, True),
    _col("profit_index", "Profit Potential", 110, "score", "center", True),
    _col("category", "Type", 100, "text", "w", True),
    _col("total_cost", "Trip Cost (USD)", 112, "money"),
    # Available from the Columns menu.
    _col("cost_per_unit", "Cost / unit", 96, "money2"),
    _col("roi", "ROI", 80, "money2"),
    _col("units", "Units sold (est.)", 118, "int"),
    _col("exhibitors", "Exhibitors", 96, "int"),
    _col("drive_hours", "Drive time", 96, "hours"),
    _col("distance_miles", "Miles", 84, "int"),
    _col("deadline", "Apply by", 110),
    _col("admission", "Admission", 110),
    _col("venue", "Venue", 180),
    _col("promoter", "Promoter", 170),
    _col("juried", "Juried", 90),
    _col("url", "Listing URL", 280),
)

COLUMN_BY_KEY = {c.key: c for c in COLUMNS}
DEFAULT_COLUMNS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.default)


def unit_name() -> str:
    """What the vendor sells one of — "jar" for the shipped profile."""
    return config.UNIT_NAME


def column_title(key: str) -> str:
    """Column heading, with the business's unit noun substituted in."""
    title = COLUMN_BY_KEY[key].title
    return title.replace("unit", unit_name())


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def relative_index(value: float, best: float) -> float:
    """Map a raw score onto a 0-100 index against the best in the set.

    The scoring model's output is unbounded dollars-times-root-ROI, which
    is meaningless on its own row.  What a reader wants is "how does this
    show compare with the best one I found", so the index is *relative to
    the current result set*: 100 is the top show, 0 is anything that loses
    money.  The log keeps one runaway outlier from flattening everything
    below it into a row of 3s.
    """
    if best <= 0 or value <= 0:
        return 0.0
    return round(100.0 * math.log1p(value) / math.log1p(best), 1)


def _fmt_dates(s: ScoredEvent) -> str:
    # strftime's %-d is not portable to Windows, so build the day numbers
    # by hand rather than shelling out to platform-specific format codes.
    start, end = s.event.start_date, s.event.end_date
    if start is None:
        return "—"
    if end and end != start:
        if (end.year, end.month) == (start.year, start.month):
            return f"{start:%b} {start.day} - {end.day}, {start.year}"
        return f"{start:%b} {start.day} - {end:%b} {end.day}, {end.year}"
    return f"{start:%b} {start.day}, {start.year}"


@dataclass
class Row:
    """One scored event, plus everything the table needs to draw it."""

    scored: ScoredEvent
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def event(self):
        return self.scored.event

    @property
    def breakdown(self):
        return self.scored.breakdown

    @property
    def key(self) -> str:
        return self.scored.event.event_id

    def get(self, column: str) -> Any:
        return self.values.get(column)

    def text(self, column: str) -> str:
        """The cell as drawn.

        A leading ``~`` marks a number the scraper estimated rather than
        read off the listing — the booth fee behind FestivalNet's Pro wall
        and the attendance of a show that publishes none.  Without the mark
        a tier estimate reads as a quoted price.
        """
        value = format_value(COLUMN_BY_KEY[column].kind, self.values.get(column))
        if value == "—":
            return value
        if column == "booth_fee" and self.values.get("booth_fee_estimated"):
            return "~" + value
        if column == "attendance" and self.values.get("attendance_estimated"):
            return "~" + value
        return value

    def search_blob(self) -> str:
        e = self.event
        return " ".join(str(x) for x in (
            e.name, e.city, e.state, e.venue, e.address, e.promoter,
            e.description, self.values.get("category", ""),
        ) if x).lower()

    def location_blob(self) -> str:
        e = self.event
        return " ".join(str(x) for x in (
            e.city, e.state, e.zip_code, e.venue, e.address,
        ) if x).lower()


def build_rows(scored: Sequence[ScoredEvent]) -> list[Row]:
    """Turn scored events into table rows, indexing the two 0-100 scores."""
    best_score = max((s.breakdown.score for s in scored), default=0.0)
    best_profit = max((s.breakdown.est_profit for s in scored), default=0.0)
    rows: list[Row] = []
    for s in scored:
        e, b = s.event, s.breakdown
        cost_per_unit = b.cost_per_jar
        if cost_per_unit in (None, float("inf")):
            cost_per_unit = None
        rows.append(Row(s, {
            "overall": relative_index(b.score, best_score),
            "profit_index": relative_index(b.est_profit, best_profit),
            "name": e.name,
            "city": e.city,
            "state": e.state,
            "dates": _fmt_dates(s),
            "start_date": e.start_date,
            "end_date": e.end_date or e.start_date,
            "attendance": b.est_attendance or e.attendance,
            "attendance_estimated": b.attendance_estimated,
            "exhibitors": b.est_exhibitors or e.exhibitors,
            "booth_fee": b.booth_fee,
            "booth_fee_estimated": b.booth_fee_estimated,
            "gross_revenue": b.gross_revenue,
            "total_cost": b.total_cost,
            "est_profit": b.est_profit,
            "roi": b.roi if b.roi not in (None, float("inf")) else None,
            "units": b.jars_sold,
            "cost_per_unit": cost_per_unit,
            "drive_hours": e.drive_hours,
            "distance_miles": e.distance_miles,
            "deadline": _deadline_text(e.deadlines),
            "deadline_date": deadline_date(e.deadlines),
            "admission": e.admission or "—",
            "venue": e.venue or "—",
            "promoter": e.promoter or "—",
            "juried": e.juried or "—",
            "url": e.url,
            "category": categories.classify(e.category_slug).label,
            "category_key": categories.category_key(e.category_slug),
            "raw_score": b.score,
        }))
    return rows


def _deadline_text(deadlines: str) -> str:
    when = deadline_date(deadlines)
    if when is not None:
        return f"{when:%b} {when.day}, {when.year}"
    return (deadlines or "—").strip() or "—"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_value(kind: str, value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return "—"
    if kind == "money":
        return f"${value:,.0f}"
    if kind == "money2":
        return f"${value:,.2f}"
    if kind == "int":
        return f"{round(value):,}"
    if kind == "score":
        return f"{value:.1f}"
    if kind == "hours":
        return f"{value:.1f} h"
    return str(value)


def compact_money(value: float) -> str:
    """`$8,742,650` shortened for a stat card that has 150px to say it in."""
    if value is None:
        return "—"
    # Whole dollars for as long as they fit the card; only billions get
    # abbreviated, because "$8,742,650" is the number people quote.
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f}B"
    return f"${value:,.0f}"


def compact_count(value: float) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M+"
    if value >= 100_000:
        return f"{value / 1_000:,.0f}K+"
    return f"{round(value):,}"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

ALL_COUNTRIES = "All Countries"
ALL_STATES = "All States / Provinces"
ALL_TYPES = "All Event Types"


@dataclass
class Filters:
    """The left rail's search panel, as data.

    Applied to rows already in memory — the crawl scope (which states,
    how many weeks) is a separate concern handled by
    :func:`fnscraper.gui.scrape.settings_for`.
    """

    keyword: str = ""
    location: str = ""
    country: str = ALL_COUNTRIES
    state: str = ALL_STATES
    event_type: str = ALL_TYPES
    date_from: date | None = None
    date_to: date | None = None
    min_attendance: int | None = None
    max_attendance: int | None = None
    use_dates: bool = True
    use_location: bool = True
    exact_match: bool = False
    include_past: bool = True

    def matches(self, row: Row, today: date | None = None) -> bool:
        today = today or date.today()
        if self.keyword and not _keyword_hit(
                self.keyword, row.search_blob(), self.exact_match):
            return False
        if self.use_location and self.location and not _keyword_hit(
                self.location, row.location_blob(), self.exact_match):
            return False
        if self.state not in ("", ALL_STATES) and \
                row.event.state.upper() != _state_code(self.state).upper():
            return False
        if self.event_type not in ("", ALL_TYPES) and \
                row.get("category_key") != self.event_type:
            return False

        start = row.get("start_date")
        end = row.get("end_date") or start
        if self.use_dates and (self.date_from or self.date_to):
            if start is None:
                return False
            if self.date_from and (end or start) < self.date_from:
                return False
            if self.date_to and start > self.date_to:
                return False
        if not self.include_past and end is not None and end < today:
            return False

        attendance = row.get("attendance") or 0
        if self.min_attendance is not None and attendance < self.min_attendance:
            return False
        if self.max_attendance is not None and attendance > self.max_attendance:
            return False
        return True

    def apply(self, rows: Iterable[Row], today: date | None = None) -> list[Row]:
        today = today or date.today()
        return [r for r in rows if self.matches(r, today)]

    def cleared(self) -> "Filters":
        return replace(Filters(), use_dates=self.use_dates,
                       use_location=self.use_location)


def _keyword_hit(needle: str, haystack: str, exact: bool) -> bool:
    """Substring match, or whole-phrase match when Exact Match is on.

    "Exact" here means the phrase stands on its own — searching *art* stops
    matching "Smart Living Expo" — rather than case-sensitivity, which is
    never what someone typing into a search box wants.
    """
    needle = needle.strip().lower()
    if not needle:
        return True
    if not exact:
        return needle in haystack
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _state_code(label: str) -> str:
    """"Ohio (OH)" -> "OH"; a bare code passes straight through."""
    match = re.search(r"\(([A-Z]{2})\)\s*$", label)
    return match.group(1) if match else label.strip()


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

SORT_ORDERS: tuple[tuple[str, str], ...] = (
    ("best", "Best Shows (Overall Score)"),
    ("profit", "Most Profitable Show Potential"),
    ("attendance", "Highest Attendance"),
    ("booth_fee", "Lowest Booth Fee"),
    ("total_cost", "Lowest Total Trip Cost"),
    ("date", "Closest To Date"),
    ("deadline", "Application Deadline First"),
    ("name", "A to Z"),
)
SORT_LABELS = dict(SORT_ORDERS)
DEFAULT_SORT = "best"

_BIG = float("inf")


def _num(value, default=0.0) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(number) else number


def sort_rows(rows: Sequence[Row], order: str = DEFAULT_SORT) -> list[Row]:
    """Order rows for one of the rail's ranking choices.

    Every ordering ends in the show's name so a redraw never shuffles rows
    that tie — a table that reorders under the cursor is unusable.
    """
    name = lambda r: r.event.name.lower()
    if order == "profit":
        return sorted(rows, key=lambda r: (-_num(r.get("est_profit")), name(r)))
    if order == "attendance":
        return sorted(rows, key=lambda r: (-_num(r.get("attendance")), name(r)))
    if order == "booth_fee":
        return sorted(rows, key=lambda r: (_num(r.get("booth_fee"), _BIG), name(r)))
    if order == "total_cost":
        return sorted(rows, key=lambda r: (_num(r.get("total_cost"), _BIG), name(r)))
    if order == "date":
        return sorted(rows, key=lambda r: (r.get("start_date") or date.max, name(r)))
    if order == "deadline":
        return sorted(rows, key=lambda r: (r.get("deadline_date") or date.max,
                                           r.get("start_date") or date.max, name(r)))
    if order == "name":
        return sorted(rows, key=name)
    return sorted(rows, key=lambda r: (-_num(r.get("overall")), name(r)))


def sort_by_column(rows: Sequence[Row], column: str, descending: bool) -> list[Row]:
    """Sort by a clicked column heading, keeping empty cells at the bottom."""
    spec = COLUMN_BY_KEY[column]
    if spec.numeric:
        def key(row):
            value = row.get(column)
            missing = value is None
            number = _num(value)
            return (missing, -number if descending else number)
    else:
        def key(row):
            value = row.text(column)
            return (value in ("", "—"), value.lower())
    ordered = sorted(rows, key=key)
    if descending and not spec.numeric:
        head = [r for r in ordered if r.text(column) not in ("", "—")]
        tail = [r for r in ordered if r.text(column) in ("", "—")]
        ordered = list(reversed(head)) + tail
    return ordered


# ---------------------------------------------------------------------------
# Headline numbers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Summary:
    count: int = 0
    states: int = 0
    cities: int = 0
    total_booth_fee: float = 0.0
    total_revenue: float = 0.0
    total_profit: float = 0.0
    total_attendance: float = 0.0
    total_cost: float = 0.0


def summarize(rows: Sequence[Row]) -> Summary:
    if not rows:
        return Summary()
    return Summary(
        count=len(rows),
        states=len({r.event.state for r in rows if r.event.state}),
        cities=len({(r.event.city, r.event.state) for r in rows if r.event.city}),
        total_booth_fee=sum(_num(r.get("booth_fee")) for r in rows),
        total_revenue=sum(_num(r.get("gross_revenue")) for r in rows),
        total_profit=sum(_num(r.get("est_profit")) for r in rows),
        total_attendance=sum(_num(r.get("attendance")) for r in rows),
        total_cost=sum(_num(r.get("total_cost")) for r in rows),
    )


def cards_for(summary: Summary) -> list[tuple[str, str, str]]:
    """(value, label, icon) for the six overview cards, left to right."""
    return [
        (f"{summary.count:,}", "Festivals Found", "calendar"),
        (f"{summary.states:,}", "States", "globe"),
        (f"{summary.cities:,}", "Cities", "building"),
        (compact_money(summary.total_booth_fee), "Booth Fees (USD)", "dollar"),
        (compact_money(summary.total_revenue), "Est. Revenue (USD)", "chart"),
        (compact_count(summary.total_attendance), "Attendance Potential",
         "people"),
    ]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 10


def page_count(total: int, per_page: int = DEFAULT_PAGE_SIZE) -> int:
    per_page = max(1, per_page)
    return max(1, math.ceil(total / per_page))


def page_slice(rows: Sequence[Row], page: int,
               per_page: int = DEFAULT_PAGE_SIZE) -> list[Row]:
    per_page = max(1, per_page)
    page = clamp_page(page, page_count(len(rows), per_page))
    start = (page - 1) * per_page
    return list(rows[start:start + per_page])


def clamp_page(page: int, pages: int) -> int:
    return max(1, min(int(page), max(1, pages)))


def page_range_text(total: int, page: int, per_page: int) -> str:
    if total == 0:
        return "No festivals to show"
    page = clamp_page(page, page_count(total, per_page))
    first = (page - 1) * per_page + 1
    last = min(total, page * per_page)
    return f"Showing {first:,} to {last:,} of {total:,} festivals"


def page_numbers(page: int, pages: int, window: int = 5) -> list[int | None]:
    """Page buttons for the pager; ``None`` renders as an ellipsis.

    Always shows the first ``window`` pages around the current one plus the
    last page, which is what the mockup's `1 2 3 4 5 … 24` bar is.
    """
    pages = max(1, pages)
    page = clamp_page(page, pages)
    if pages <= window + 2:
        return list(range(1, pages + 1))
    half = window // 2
    start = max(1, min(page - half, pages - window + 1))
    end = min(pages, start + window - 1)

    numbers: list[int | None] = []
    if start > 1:
        numbers.append(1)
        if start > 2:
            numbers.append(None)
    numbers.extend(range(start, end + 1))
    if end < pages:
        if end < pages - 1:
            numbers.append(None)
        numbers.append(pages)
    return numbers

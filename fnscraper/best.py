"""Build a bookable weekend-by-weekend show plan and export it as CSV.

This is the "one button" report: for every weekend in the next N months it
picks the ``top`` most profitable shows that are still open for
applications, and writes them to

    reports/josemadridsalsa/export<MMDDYY>-<MMDDYY>/export<MMDDYY>-<MMDDYY>.csv

with the exact column set the Jose Madrid Salsa admin panel imports.  The
date stamps in the directory/file name are the first and last event date
the file actually covers, so two exports never collide.

Selection rules
---------------
* the show must run on at least one bookable weekday (Wed-Sun); a show that
  only runs Mon/Tue is dead for a retail booth and is dropped outright
* shows that miss the prime days (Fri/Sat/Sun) are ranked as if worth
  ``OFF_WEEKEND_PENALTY`` of their score, so they only win a slot when
  nothing better is on that weekend
* a show whose application deadline has already passed is dropped
* one show can hold a slot on at most ``max_repeats`` weekends, so a
  weekly market can't quietly fill the whole quarter
"""

from __future__ import annotations

import csv
import dataclasses
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from . import config
from .models import ScoredEvent
from .tui import _parsed_deadlines, deadline_date

log = logging.getLogger(__name__)

# The admin-panel import format.  Order is significant — see SPEC.md.
COLUMNS = [
    "Event Name",
    "Venue",
    "Address",
    "City",
    "ST",
    "Drive-Time",
    "Start Date",
    "End Date",
    "Times",
    "Application Deadline",
    "Booth Fee",
    "Attendance",
    "# of Exhibitors",
    "Cost of Fuel",
    "Lodging",
    "Meals",
    "Contact Name",
    "Contact Email Address",
    "Application Information",
    "URL of Festivalnet posting",
]

ESTIMATE_MARK = "*"

_IMPORT_FORMAT = "integrations/josemadridsalsa/IMPORT_FORMAT.md"


# ---------------------------------------------------------------------------
# Weekend maths
# ---------------------------------------------------------------------------

def saturday_of(day: date) -> date:
    """The Saturday that anchors ``day``'s weekend (Sunday looks back)."""
    if day.weekday() == 6:                    # Sunday belongs to the day before
        return day - timedelta(days=1)
    return day + timedelta(days=(5 - day.weekday()) % 7)


def add_months(day: date, months: int) -> date:
    """``day`` shifted by whole months, clamped to the end of the month."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def weekend_slots(event) -> dict[date, set[int]]:
    """Weekend anchor -> the bookable weekdays the show covers that weekend."""
    open_days = event.open_weekdays()
    slots: dict[date, set[int]] = {}
    for day in event.running_dates():
        if open_days is not None and day.weekday() not in open_days:
            continue
        if day.weekday() in config.BOOKABLE_WEEKDAYS:
            slots.setdefault(saturday_of(day), set()).add(day.weekday())
    return slots


def weekend_multiplier(weekdays: set[int]) -> float:
    """Full credit for a show touching Fri/Sat/Sun, a haircut otherwise."""
    if weekdays & config.PRIME_WEEKDAYS:
        return config.PRIME_WEEKEND_BONUS
    return config.OFF_WEEKEND_PENALTY


def deadline_passed(event, today: date) -> bool:
    """True when every way into the show has already closed.

    A salsa booth can go in on the craft/exhibitor track or the food track,
    so one closed track doesn't close the show — an open-ended "until full"
    on the other one keeps it bookable.
    """
    for text in (event.exhibit_deadline, event.food_deadline):
        text = (text or "").strip()
        if not text or text.lower() in ("na", "n/a", "none"):
            continue
        if not _parsed_deadlines(text, today):
            return False                      # "until full" — still open
    parsed = _parsed_deadlines(event.deadlines, today)
    if not parsed:
        return False                          # nothing published
    return all(d < today for d in parsed)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Slot:
    weekend: date
    scored: ScoredEvent
    weekdays: set[int]
    slot_score: float

    @property
    def days(self) -> list[date]:
        """The actual dates this slot books, within its weekend."""
        # ``weekend`` is the Saturday, i.e. weekday 5.
        return sorted(self.weekend + timedelta(days=w - 5) for w in self.weekdays)


def build_plan(
    scored: list[ScoredEvent],
    months: int = config.BEST_MONTHS_AHEAD,
    top: int = config.BEST_TOP_PER_WEEKEND,
    today: date | None = None,
    max_repeats: int = 2,
) -> list[Slot]:
    """Pick the ``top`` best bookable shows for each weekend in the window."""
    today = today or date.today()
    horizon = add_months(today, months)

    candidates: dict[date, list[Slot]] = {}
    for s in scored:
        event = s.event
        if event.start_date is None or s.breakdown.est_profit <= 0:
            continue
        if (event.end_date or event.start_date) < today:
            continue                          # already over
        if deadline_passed(event, today):
            continue
        for weekend, weekdays in weekend_slots(event).items():
            # A weekend counts until its Sunday is over, so a plan built on
            # a Saturday still offers that same day.
            if weekend + timedelta(days=1) < today or weekend > horizon:
                continue
            candidates.setdefault(weekend, []).append(
                Slot(weekend, s, weekdays,
                     s.breakdown.score * weekend_multiplier(weekdays))
            )

    plan: list[Slot] = []
    used: dict[str, int] = {}
    for weekend in sorted(candidates):
        picked = 0
        for slot in sorted(candidates[weekend],
                           key=lambda x: x.slot_score, reverse=True):
            if picked >= top:
                break
            event_id = slot.scored.event.event_id
            if used.get(event_id, 0) >= max_repeats:
                continue
            used[event_id] = used.get(event_id, 0) + 1
            plan.append(slot)
            picked += 1
        if picked < top:
            log.info("weekend of %s: only %d qualifying show(s)", weekend, picked)
    return plan


# ---------------------------------------------------------------------------
# Cell formatting
# ---------------------------------------------------------------------------

def _money(value: float | None, estimated: bool = False) -> str:
    if value is None:
        return ""
    return f"${value:,.2f}" + (ESTIMATE_MARK if estimated else "")


def _count(value: int | None, estimated: bool) -> str:
    if value is None:
        return ""
    return f"{value}" + (ESTIMATE_MARK if estimated else "")


def _us_date(day: date | None) -> str:
    return day.strftime("%m/%d/%Y") if day else ""


def drive_time(hours: float | None) -> str:
    """3.7 -> '3h 42m'.  One way, from the home base in config."""
    if hours is None:
        return ""
    total = int(round(hours * 60))
    return f"{total // 60}h {total % 60:02d}m"


_TRACKS = r"Art\s*&\s*Craft|Exhibitor|Food|Music|Entertainment"
# Each track runs until the next track label — anything else with a colon in
# it ("until full Music:") belongs to the value, not to a new segment.
_DEADLINE_SEGMENT_RE = re.compile(
    rf"({_TRACKS})\s*:\s*(.*?)(?=\s*(?:{_TRACKS})\s*:|$)", re.I
)


def application_deadline(event, today: date) -> str:
    """The exhibitor deadline: a real date if there is one, else its words.

    Anonymous listings jam every track into one string ("Art & Craft: until
    full Music: 5/1/2026 Food: na"); a salsa booth applies on the art/craft
    or food track, so pull those out rather than printing the lot.
    """
    for text in (event.exhibit_deadline, event.food_deadline):
        if text and text.strip().lower() not in ("na", "n/a", ""):
            parsed = deadline_date(text, today)
            return _us_date(parsed) if parsed else text.strip()

    segments = {
        key.lower().replace(" ", ""): value.strip()
        for key, value in _DEADLINE_SEGMENT_RE.findall(event.deadlines or "")
    }
    for key in ("art&craft", "exhibitor", "food"):
        value = segments.get(key, "")
        if value and value.lower() not in ("na", "n/a"):
            parsed = deadline_date(value, today)
            return _us_date(parsed) if parsed else value

    upcoming = deadline_date(event.deadlines or "", today)
    return _us_date(upcoming) if upcoming else "Not listed"


def address_cell(event) -> str:
    """A single mailing line, however the source split it up.

    Anonymous listings already carry ", City, ST ZIP"; Pro pages give the
    street on its own with the ZIP in the header block.
    """
    street = (event.address or "").strip().rstrip(",")
    if not street:
        return ""
    if event.city and event.city.lower() in street.lower():
        return street
    region = " ".join(x for x in (event.state, event.zip_code) if x)
    tail = ", ".join(p for p in (event.city, region) if p)
    return f"{street}, {tail}" if tail else street


def booth_fee_cell(s: ScoredEvent) -> str:
    """The fee used in the P&L, marked when it's a tier estimate.

    A Pro listing that says "Contact" rather than a number still gets the
    estimate, but the promoter's own wording is preserved beside it so you
    know to ask.
    """
    fee = _money(s.breakdown.booth_fee, s.breakdown.booth_fee_estimated)
    text = (s.event.booth_fee_text or "").strip()
    if s.breakdown.booth_fee_estimated and text and text.lower() not in (
        "na", "n/a", "none", "", "-"
    ) and "$" not in text:
        return f"{fee} ({text})"
    return fee


def contact_name(event) -> str:
    return event.contact_name or event.promoter or ""


def application_information(event) -> str:
    bits = [b for b in (event.application_info, event.promoter_website) if b]
    return " — ".join(bits) if bits else "See FestivalNet listing"


def row_for(s: ScoredEvent, today: date | None = None) -> list[str]:
    """One CSV record, in ``COLUMNS`` order."""
    today = today or date.today()
    e, b = s.event, s.breakdown
    return [
        e.name,
        e.venue,
        address_cell(e),
        e.city,
        e.state,
        drive_time(e.drive_hours),
        _us_date(e.start_date),
        _us_date(e.end_date or e.start_date),
        e.hours_text,
        application_deadline(e, today),
        booth_fee_cell(s),
        _count(b.est_attendance, b.attendance_estimated),
        _count(b.est_exhibitors, b.exhibitors_estimated),
        _money(b.fuel_cost),
        _money(b.lodging_cost),
        _money(b.meals_cost),
        contact_name(e),
        e.contact_email,
        application_information(e),
        e.url,
    ]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_stem(plan: list[Slot]) -> str:
    """``export<MMDDYY>-<MMDDYY>`` spanning the days the plan books.

    Deliberately the *booked* days rather than the events' own date ranges:
    one market that runs until New Year would otherwise stamp a three-month
    plan as if it covered six.
    """
    days = [day for slot in plan for day in slot.days]
    if not days:
        today = date.today()
        return f"export{today:%m%d%y}-{today:%m%d%y}"
    return f"export{min(days):%m%d%y}-{max(days):%m%d%y}"


def export_plan(
    plan: list[Slot],
    base_dir: str | Path = config.BEST_EXPORT_DIR,
    today: date | None = None,
) -> Path:
    """Write the plan's CSV (plus its column spec) and return the CSV path."""
    today = today or date.today()
    stem = export_stem(plan)
    out_dir = Path(base_dir) / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"

    # utf-8-sig: Excel needs the BOM to read the accented promoter names.
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL,
                            lineterminator="\r\n")
        writer.writerow(COLUMNS)
        for slot in plan:
            writer.writerow(row_for(slot.scored, today))

    (out_dir / "SPEC.md").write_text(spec_markdown(), encoding="utf-8")
    # Ship the full importer contract beside the data so whoever wires up
    # the admin panel is never working from a stale copy.
    contract = Path(__file__).resolve().parent.parent / _IMPORT_FORMAT
    if contract.is_file():
        (out_dir / contract.name).write_text(
            contract.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return csv_path


def spec_markdown() -> str:
    """The import contract, written next to every export."""
    rows = "\n".join(
        f"| {i} | {name} | {desc} |"
        for i, (name, desc) in enumerate(zip(COLUMNS, _COLUMN_NOTES), start=1)
    )
    return _SPEC_TEMPLATE.format(rows=rows, header=",".join(COLUMNS))


_COLUMN_NOTES = [
    "Show name as listed on FestivalNet. Free text.",
    "Venue / grounds name. May be empty when the listing omits it.",
    "Full mailing line: street, city, ST ZIP. May be empty.",
    "City.",
    "Two-letter state code.",
    "One-way drive time from Zanesville, OH. Format `Hh MMm`, e.g. `3h 42m`.",
    "First day of the show. `MM/DD/YYYY`.",
    "Last day of the show. `MM/DD/YYYY`. Equals Start Date for one-day shows.",
    "Opening hours as published, e.g. `Sat 10am-6pm; Sun 11am-5pm`. Free text.",
    "`MM/DD/YYYY` when the promoter published a date, otherwise their own "
    "wording (`until full`) or `Not listed`.",
    "Booth fee in `$0.00`. A trailing `*` means it is a tier estimate, not a "
    "published fee; a trailing `(...)` repeats the promoter's wording.",
    "Expected attendance. Trailing `*` means estimated.",
    "Number of exhibitor booths. Trailing `*` means estimated.",
    "Round-trip fuel cost, `$0.00`.",
    "Lodging cost for the trip, `$0.00`. `$0.00` means it is a day trip.",
    "Per-diem meal cost for the trip, `$0.00`.",
    "Show/exhibit director, falling back to the promoter organisation.",
    "Promoter email. Empty when FestivalNet does not publish one.",
    "How to get the application, plus the promoter's website when known.",
    "Canonical FestivalNet listing URL. Use as the natural key on re-import.",
]

_SPEC_TEMPLATE = """# Jose Madrid Salsa — show import format

One row per show. UTF-8 with BOM, `\\r\\n` line endings, RFC-4180 quoting
(only fields containing a comma, quote, or newline are quoted).

## Header row

```
{header}
```

## Columns

| # | Column | Meaning |
|---|--------|---------|
{rows}

## Parsing notes

* **Money** — `$` prefix, thousands separators, two decimals. Strip
  `[$,*]` and any trailing ` (...)` before `parseFloat`.
* **The `*` suffix** — the value is the scraper's estimate because
  FestivalNet did not publish it. Treat those rows as needing confirmation
  before you commit to the show.
* **Drive-Time** — `/^(\\d+)h\\s*(\\d+)m$/`; minutes are zero-padded.
* **Dates** — always `MM/DD/YYYY`. Application Deadline is the only date
  column that can hold non-date text.
* **Natural key** — `URL of Festivalnet posting` is stable across exports;
  upsert on it rather than on the event name.
* **Empty cells** — mean "not published", never zero.
"""

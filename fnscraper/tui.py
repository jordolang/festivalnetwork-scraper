"""Interactive terminal picker for scraped shows.

A scrolling checkbox list, sorted by state, then date, then out-of-pocket
cost.  Each row shows the estimated out-of-pocket **cost to sell one jar
of salsa**, the **booth-space fee on its own**, the total cost of doing
the show, the location, date, and name.  A ``~`` in front of the booth
fee marks an estimate (no Pro login); a bare ``$`` is a real fee scraped
from a logged-in session.

Keys:
    UP/DOWN, PgUp/PgDn, Home/End   scroll
    SPACE                           check/uncheck the show next to the cursor
    o                               toggle event-date/deadline ordering
    d                               open the event-detail popup for the row
    ENTER or s                      save checked shows and exit
    q or ESC                        exit without saving
"""

from __future__ import annotations

import curses
import re
import textwrap
from datetime import date, datetime
from typing import NamedTuple

from .models import ScoredEvent

HELP_LINE = (
    "SPACE select   o order: event/deadline   d details   ENTER save+exit   "
    "q quit without saving   up/down scroll"
)
HEADER_FMT = "    {st:2}  {deadline:11}  {date:11}  {cpj:>9}  {booth:>8}  {cost:>9}  {drive:>6}  {name}"


class DetailLine(NamedTuple):
    """One rendered line of the detail popup.

    ``bold`` marks section headers; ``indent`` is the left padding applied
    to *continuation* lines when a long value gets word-wrapped, so wrapped
    text stays aligned under its label.
    """

    text: str
    bold: bool = False
    indent: int = 0


_LABEL_W = 14   # column width for "Label   value" field rows


def _money(v: float | None) -> str:
    if v is None or v == float("inf"):
        return "n/a"
    return f"${v:,.2f}"


def _count(v: int | None, estimated: bool) -> str:
    if v is None:
        return "n/a"
    return f"{v:,}" + ("  (est.)" if estimated else "")


def _detail_lines(s: ScoredEvent) -> list[DetailLine]:
    """Build the popup's content for one show, mirroring the layout of a
    FestivalNet detail page: identity, when, where, the crowd, the money.

    ─────────────────────────────────────────────────────────────────────
    THIS is the function to make your own.  Everything below is a working
    default, but *which* fields matter — and in what order — is a judgment
    call only you can make as the vendor.  When you scan a listing on
    festivalnet.com, what do your eyes jump to first?  Attendance?  Booth
    fee?  Drive time?  Reorder the sections, drop fields you never read,
    or promote the numbers you actually decide on.  The renderer wraps and
    scrolls whatever you return, so you can't break the layout.
    ─────────────────────────────────────────────────────────────────────
    """
    e, b = s.event, s.breakdown
    out: list[DetailLine] = []

    def head(text: str) -> None:
        if out:
            out.append(DetailLine(""))            # blank spacer above headers
        out.append(DetailLine(text, bold=True))

    def field(label: str, value: str) -> None:
        out.append(DetailLine(f"{label + ':':<{_LABEL_W}}{value}", indent=_LABEL_W))

    # Identity
    out.append(DetailLine(e.name, bold=True))
    if e.category_slug:
        out.append(DetailLine(e.category_slug.replace("-", " ")))
    if e.stale_listing:
        out.append(DetailLine("⚠ listing looks stale — verify before applying"))

    # When
    head("WHEN")
    when = f"{e.start_date:%a %b %d, %Y}" if e.start_date else "date TBD"
    if e.end_date and e.end_date != e.start_date:
        when += f"  →  {e.end_date:%a %b %d, %Y}"
    if e.unconfirmed_date:
        when += "  (unconfirmed)"
    field("Dates", when)
    if e.hours_text:
        field("Hours", e.hours_text)

    # Where
    head("WHERE")
    field("Location", ", ".join(p for p in (e.city, e.state) if p) or "TBD")
    if e.venue:
        field("Venue", e.venue)
    if e.address:
        field("Address", e.address)
    if e.drive_hours is not None:
        drive = f"{e.drive_hours:.1f} h one-way"
        if e.distance_miles is not None:
            drive += f"  ({e.distance_miles:.0f} mi)"
        field("Drive", drive)

    # The crowd
    head("THE CROWD")
    field("Admission", e.admission or "n/a")
    att = e.attendance if e.attendance is not None else b.est_attendance
    field("Attendance", _count(att, b.attendance_estimated or e.attendance is None))
    exh = e.exhibitors if e.exhibitors is not None else b.est_exhibitors
    field("Exhibitors", _count(exh, b.exhibitors_estimated or e.exhibitors is None))
    field("Food booths", _count(e.food_booths, estimated=False))
    if e.juried:
        field("Juried", e.juried)
    if e.deadlines:
        field("Deadlines", e.deadlines)
    if e.promoter:
        field("Promoter", e.promoter)

    # Fees (member-only on FestivalNet)
    head("BOOTH FEES")
    if e.exhib_fee is not None or e.food_fee is not None:
        if e.exhib_fee is not None:
            field("Exhibitor", _money(e.exhib_fee))
        if e.food_fee is not None:
            field("Food vendor", _money(e.food_fee))
    else:
        out.append(DetailLine("member login required — using estimate below"))

    # The money — your profitability model
    head("PROFITABILITY (estimated)")
    field("Jars sold", f"{b.jars_sold:,.0f}")
    field("Gross rev", _money(b.gross_revenue))
    field("COGS", _money(b.cogs))
    booth = _money(b.booth_fee) + ("  (est.)" if b.booth_fee_estimated else "")
    field("Booth fee", booth)
    field("Fuel", _money(b.fuel_cost))
    field("Lodging", _money(b.lodging_cost))
    field("Meals", _money(b.meals_cost))
    field("Total cost", _money(b.total_cost))
    field("Est. profit", _money(b.est_profit))
    field("ROI", f"{b.roi:.2f}x per out-of-pocket $")
    field("Cost / jar", _money(b.cost_per_jar))
    field("Score", f"{b.score:.1f}")

    if b.notes:
        head("NOTES")
        for note in b.notes:
            out.append(DetailLine(f"- {note}", indent=2))

    if e.description:
        head("DESCRIPTION")
        for para in e.description.splitlines():
            out.append(DetailLine(para.strip()))

    head("SOURCE")
    field("URL", e.url)
    return out


_DEADLINE_PATTERNS = (
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?\b",
)


def deadline_date(text: str, today: date | None = None) -> date | None:
    """Return the earliest upcoming date found in deadline text."""
    today = today or date.today()
    found: list[date] = []
    for pattern in _DEADLINE_PATTERNS:
        for raw in re.findall(pattern, text, flags=re.I):
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y",
                        "%B %d", "%b %d"):
                try:
                    parsed = datetime.strptime(raw, fmt).date()
                    if "%Y" not in fmt and "%y" not in fmt:
                        parsed = parsed.replace(year=today.year)
                        if parsed < today:
                            parsed = parsed.replace(year=today.year + 1)
                    found.append(parsed)
                    break
                except ValueError:
                    continue
    upcoming = [d for d in found if d >= today]
    return min(upcoming) if upcoming else None


def filter_by_deadline(scored: list[ScoredEvent], deadline_by: date,
                       today: date | None = None) -> list[ScoredEvent]:
    """Keep events with a known, open application deadline by ``deadline_by``."""
    today = today or date.today()
    return [
        s for s in scored
        if (deadline := deadline_date(s.event.deadlines, today)) is not None
        and deadline <= deadline_by
    ]


def sort_for_picker(scored: list[ScoredEvent], order: str = "event") -> list[ScoredEvent]:
    """State, then date, then out-of-pocket cost — the requested order."""
    if order == "deadline":
        return sorted(scored, key=lambda s: (
            deadline_date(s.event.deadlines) or date.max,
            s.event.start_date or date.max,
            s.event.state or "~",
            s.breakdown.total_cost,
        ))
    return sorted(
        scored,
        key=lambda s: (
            s.event.state or "~",
            s.event.start_date or date.max,
            s.breakdown.total_cost,
        ),
    )


def format_row(s: ScoredEvent, checked: bool) -> str:
    e, b = s.event, s.breakdown
    cpj = f"${b.cost_per_jar:,.2f}" if b.cost_per_jar != float("inf") else "n/a"
    when = f"{e.start_date:%b %d}" if e.start_date else "?"
    if e.end_date and e.end_date != e.start_date:
        when += f"-{e.end_date:%d}"
    mark = "[x]" if checked else "[ ]"
    deadline = deadline_date(e.deadlines)
    deadline_text = f"{deadline:%b %d}" if deadline else "?"
    name = f"{e.name} — {e.city}"
    # Booth-space fee on its own; ~ marks an estimate (see module docstring).
    booth = f"${b.booth_fee:,.0f}"
    if b.booth_fee_estimated:
        booth = "~" + booth
    cost = f"${b.total_cost:,.0f}"
    drive = f"{e.drive_hours or 0:.1f}h"
    return (
        f"{mark} {e.state:2}  {deadline_text:11}  {when:11}  {cpj:>9}  {booth:>8}  "
        f"{cost:>9}  {drive:>6}  {name}"
    )


def _wrap_detail(lines: list[DetailLine], width: int) -> list[DetailLine]:
    """Word-wrap each logical line to ``width``, keeping bold/indent so a
    wrapped value lines up under its label and headers stay headers."""
    wrapped: list[DetailLine] = []
    for ln in lines:
        if not ln.text:
            wrapped.append(ln)
            continue
        pieces = textwrap.wrap(
            ln.text,
            width=max(1, width),
            subsequent_indent=" " * ln.indent,
        ) or [""]
        for piece in pieces:
            wrapped.append(DetailLine(piece, bold=ln.bold, indent=ln.indent))
    return wrapped


def _draw_detail(stdscr, lines: list[DetailLine], top: int) -> None:
    """Draw a centered, bordered popup showing ``lines`` scrolled to ``top``.

    The main list underneath is left untouched, so the box reads as a modal
    overlay — exactly like clicking a row on festivalnet.com.
    """
    height, width = stdscr.getmaxyx()
    box_h = min(len(lines) + 2, height - 2)
    box_w = min(80, width - 2)
    box_y = (height - box_h) // 2
    box_x = (width - box_w) // 2
    inner_h = box_h - 2

    win = curses.newwin(box_h, box_w, box_y, box_x)
    win.erase()
    win.box()

    for i in range(inner_h):
        idx = top + i
        if idx >= len(lines):
            break
        ln = lines[idx]
        attr = curses.A_BOLD if ln.bold else curses.A_NORMAL
        win.addnstr(1 + i, 2, ln.text, box_w - 4, attr)

    more_up = top > 0
    more_down = top + inner_h < len(lines)
    hint = "  up/down scroll   q/ESC/d close  "
    if more_up or more_down:
        arrows = f" {'^' if more_up else ' '}{'v' if more_down else ' '} "
        hint = arrows + hint
    win.addnstr(box_h - 1, 2, hint[: box_w - 4], box_w - 4, curses.A_DIM)
    win.refresh()


def _detail_modal(stdscr, s: ScoredEvent) -> None:
    """Nested event loop: show one show's full detail until the user closes
    it, then return control to the picker (which repaints over the box)."""
    _, width = stdscr.getmaxyx()
    lines = _wrap_detail(_detail_lines(s), min(80, width - 2) - 4)
    top = 0
    while True:
        height, _ = stdscr.getmaxyx()
        inner_h = max(1, min(len(lines) + 2, height - 2) - 2)
        top = max(0, min(top, len(lines) - inner_h))
        _draw_detail(stdscr, lines, top)

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            top = max(0, top - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            top = min(max(0, len(lines) - inner_h), top + 1)
        elif key == curses.KEY_PPAGE:
            top = max(0, top - inner_h)
        elif key == curses.KEY_NPAGE:
            top = min(max(0, len(lines) - inner_h), top + inner_h)
        elif key == curses.KEY_HOME:
            top = 0
        elif key == curses.KEY_END:
            top = max(0, len(lines) - inner_h)
        elif key in (ord("q"), ord("d"), 27, curses.KEY_ENTER, 10, 13):
            return


def _draw(stdscr, rows: list[ScoredEvent], checked: set[str],
          cursor: int, top: int, order: str) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    body_h = height - 3

    title = f" FestivalNet picks — {len(rows)} shows, {len(checked)} selected — order: {order} "
    stdscr.addnstr(0, 0, title.ljust(width - 1), width - 1, curses.A_BOLD)
    header = HEADER_FMT.format(
        st="ST", deadline="DEADLINE", date="DATE", cpj="$/JAR", booth="BOOTH $",
        cost="SHOW $", drive="DRIVE", name="EVENT"
    )
    stdscr.addnstr(1, 0, header.ljust(width - 1), width - 1, curses.A_UNDERLINE)

    for i in range(top, min(top + body_h, len(rows))):
        s = rows[i]
        line = format_row(s, s.event.event_id in checked)
        attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
        stdscr.addnstr(2 + i - top, 0, line.ljust(width - 1), width - 1, attr)

    stdscr.addnstr(height - 1, 0, HELP_LINE[: width - 1], width - 1, curses.A_DIM)
    stdscr.refresh()


def _picker(stdscr, rows: list[ScoredEvent]) -> list[ScoredEvent] | None:
    curses.curs_set(0)
    stdscr.keypad(True)
    checked: set[str] = set()
    cursor = top = 0
    order = "event"

    while True:
        height, _ = stdscr.getmaxyx()
        body_h = max(1, height - 3)
        if cursor < top:
            top = cursor
        elif cursor >= top + body_h:
            top = cursor - body_h + 1
        _draw(stdscr, rows, checked, cursor, top, order)

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(rows) - 1, cursor + 1)
        elif key == curses.KEY_PPAGE:
            cursor = max(0, cursor - body_h)
        elif key == curses.KEY_NPAGE:
            cursor = min(len(rows) - 1, cursor + body_h)
        elif key == curses.KEY_HOME:
            cursor = 0
        elif key == curses.KEY_END:
            cursor = len(rows) - 1
        elif key == ord(" "):
            eid = rows[cursor].event.event_id
            checked.symmetric_difference_update({eid})
            cursor = min(len(rows) - 1, cursor + 1)   # advance to next show
        elif key == ord("d"):
            _detail_modal(stdscr, rows[cursor])       # popup, then redraw list
        elif key == ord("o"):
            current_id = rows[cursor].event.event_id
            order = "deadline" if order == "event" else "event"
            rows[:] = sort_for_picker(rows, order)
            cursor = next(i for i, s in enumerate(rows) if s.event.event_id == current_id)
            top = cursor
        elif key in (curses.KEY_ENTER, 10, 13, ord("s")):
            return [s for s in rows if s.event.event_id in checked]
        elif key == ord("q"):
            # Bare ESC is deliberately not a quit key: arrow-key escape
            # sequences start with ESC and would trigger accidental exits
            # on terminals where keypad translation lags.
            return None


def run_picker(scored: list[ScoredEvent]) -> list[ScoredEvent] | None:
    """Open the picker.  Returns checked shows, or None if quit unsaved."""
    rows = sort_for_picker(scored)
    if not rows:
        return []
    return curses.wrapper(_picker, rows)


def print_plain_list(scored: list[ScoredEvent]) -> None:
    """Non-interactive fallback: same list, same order, no curses."""
    rows = sort_for_picker(scored)
    print(HEADER_FMT.format(
        st="ST", deadline="DEADLINE", date="DATE", cpj="$/JAR", booth="BOOTH $",
        cost="SHOW $", drive="DRIVE", name="EVENT"
    ))
    for s in rows:
        print(format_row(s, checked=False))

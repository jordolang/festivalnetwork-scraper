"""Interactive terminal picker for scraped shows.

A scrolling checkbox list, sorted by state, then date, then out-of-pocket
cost.  Each row shows the estimated out-of-pocket **cost to sell one jar
of salsa**, the total cost of doing the show, the location, date, and
name.

Keys:
    UP/DOWN, PgUp/PgDn, Home/End   scroll
    SPACE                           check/uncheck the show next to the cursor
    ENTER or s                      save checked shows and exit
    q or ESC                        exit without saving
"""

from __future__ import annotations

import curses
from datetime import date

from .models import ScoredEvent

HELP_LINE = "SPACE select   ENTER save+exit   q quit without saving   up/down scroll"
HEADER_FMT = "    {st:2}  {date:11}  {cpj:>9}  {cost:>9}  {drive:>6}  {name}"


def sort_for_picker(scored: list[ScoredEvent]) -> list[ScoredEvent]:
    """State, then date, then out-of-pocket cost — the requested order."""
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
    name = f"{e.name} — {e.city}"
    cost = f"${b.total_cost:,.0f}"
    drive = f"{e.drive_hours or 0:.1f}h"
    return f"{mark} {e.state:2}  {when:11}  {cpj:>9}  {cost:>9}  {drive:>6}  {name}"


def _draw(stdscr, rows: list[ScoredEvent], checked: set[str],
          cursor: int, top: int) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    body_h = height - 3

    title = f" FestivalNet picks — {len(rows)} shows, {len(checked)} selected "
    stdscr.addnstr(0, 0, title.ljust(width - 1), width - 1, curses.A_BOLD)
    header = HEADER_FMT.format(
        st="ST", date="DATE", cpj="$/JAR", cost="SHOW $", drive="DRIVE", name="EVENT"
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

    while True:
        height, _ = stdscr.getmaxyx()
        body_h = max(1, height - 3)
        if cursor < top:
            top = cursor
        elif cursor >= top + body_h:
            top = cursor - body_h + 1
        _draw(stdscr, rows, checked, cursor, top)

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
        st="ST", date="DATE", cpj="$/JAR", cost="SHOW $", drive="DRIVE", name="EVENT"
    ))
    for s in rows:
        print(format_row(s, checked=False))

"""Report generation: per-weekend markdown + human-readable shortlist."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import ScoredEvent


def _fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def _date_range(s: ScoredEvent) -> str:
    ev = s.event
    if ev.start_date and ev.end_date and ev.end_date != ev.start_date:
        return f"{ev.start_date:%a %b %-d} – {ev.end_date:%a %b %-d}"
    if ev.start_date:
        return f"{ev.start_date:%a %b %-d}"
    return "?"


def write_weekend_report(
    weekends: dict[date, list[ScoredEvent]],
    out_dir: Path,
    top_n: int,
    max_drive_hours: float,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "weekend_picks.md"
    lines = [
        "# Best salsa-vendor events by weekend",
        "",
        f"Ranked by estimated **profit x sqrt(profit per $1 out of pocket)** — ",
        f"biggest return for the least cash risked, within {max_drive_hours:.0f} h "
        "of Zanesville, OH.",
        "",
        "Dollar figures are *estimates* from public attendance/exhibitor data; "
        "booth fees marked `~` are tier estimates (FestivalNet Pro login "
        "unlocks real fees).",
        "",
    ]
    for saturday, group in weekends.items():
        lines.append(f"## Weekend of {saturday:%B %-d, %Y}")
        lines.append("")
        lines.append(
            "| # | Event | Dates | Where | Drive | Est. profit | "
            "Out of pocket | ROI | Attendance | Booth fee |"
        )
        lines.append("|--:|---|---|---|--:|--:|--:|--:|--:|--:|")
        for i, s in enumerate(group[:top_n], 1):
            e, b = s.event, s.breakdown
            fee = ("~" if b.booth_fee_estimated else "") + _fmt_money(b.booth_fee)
            att = f"{b.est_attendance:,}" + ("*" if b.attendance_estimated else "")
            lines.append(
                f"| {i} | [{e.name}]({e.url}) | {_date_range(s)} "
                f"| {e.city}, {e.state} | {e.drive_hours:.1f} h "
                f"| {_fmt_money(b.est_profit)} | {_fmt_money(b.total_cost)} "
                f"| {b.roi:.1f}x | {att} | {fee} |"
            )
        notes = {
            f"**{s.event.name}**: {'; '.join(s.breakdown.notes)}"
            for s in group[:top_n] if s.breakdown.notes
        }
        if notes:
            lines.append("")
            for n in sorted(notes):
                lines.append(f"- {n}")
        lines.append("")
    lines.append("---")
    lines.append("`*` attendance undisclosed, tier default used. "
                 "`~` booth fee estimated from attendance tier.")
    path.write_text("\n".join(lines))
    return path


def write_shortlist(selected: list[ScoredEvent], out_dir: Path) -> Path:
    """Human-readable summary of the shows checked in the picker."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "shortlist.md"
    lines = ["# Selected shows", ""]
    for s in selected:
        e, b = s.event, s.breakdown
        when = f"{e.start_date:%a %b %-d, %Y}" if e.start_date else "?"
        if e.end_date and e.end_date != e.start_date:
            when += f" – {e.end_date:%a %b %-d}"
        cpj = (f"${b.cost_per_jar:,.2f}"
               if b.cost_per_jar != float("inf") else "n/a")
        lines += [
            f"## {e.name}",
            f"- **When:** {when}  ({e.hours_text or 'hours n/a'})",
            f"- **Where:** {e.address or f'{e.city}, {e.state}'}"
            f"  ({e.drive_hours or 0:.1f} h drive)",
            f"- **Cost to sell one jar:** {cpj}"
            f"  |  show cost: {_fmt_money(b.total_cost)}"
            f"  (booth {_fmt_money(b.booth_fee)}"
            f"{'~' if b.booth_fee_estimated else ''}, fuel {_fmt_money(b.fuel_cost)},"
            f" lodging {_fmt_money(b.lodging_cost)}, meals {_fmt_money(b.meals_cost)})",
            f"- **Estimated:** {b.jars_sold:,.0f} jars, "
            f"{_fmt_money(b.est_profit)} profit ({b.roi:.1f}x)",
            f"- **Apply:** {e.deadlines or 'see listing'}  |  {e.url}",
            "",
        ]
    path.write_text("\n".join(lines))
    return path


def print_summary(weekends: dict[date, list[ScoredEvent]], top_n: int) -> None:
    for saturday, group in weekends.items():
        print(f"\n=== Weekend of {saturday:%b %-d, %Y} ===")
        for i, s in enumerate(group[:top_n], 1):
            e, b = s.event, s.breakdown
            print(
                f"  {i}. {e.name}  ({e.city}, {e.state}; {e.drive_hours:.1f}h)"
                f"  profit ~{_fmt_money(b.est_profit)}"
                f" on {_fmt_money(b.total_cost)} out of pocket"
                f" ({b.roi:.1f}x)"
            )

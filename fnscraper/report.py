"""Report generation: per-weekend markdown + a master CSV."""

from __future__ import annotations

import csv
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


def write_csv(scored: list[ScoredEvent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "score", "est_profit", "roi", "total_cost", "gross_revenue",
        "name", "start_date", "end_date", "city", "state",
        "drive_hours", "distance_miles", "category",
        "attendance", "exhibitors", "admission",
        "booth_fee", "booth_fee_estimated", "fuel_cost", "lodging_cost",
        "meals_cost", "juried", "deadlines", "promoter", "url", "notes",
    ]
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for s in scored:
            e, b = s.event, s.breakdown
            w.writerow([
                round(b.score, 1), round(b.est_profit, 0), round(b.roi, 2),
                round(b.total_cost, 0), round(b.gross_revenue, 0),
                e.name, e.start_date, e.end_date, e.city, e.state,
                round(e.drive_hours or 0, 1), round(e.distance_miles or 0),
                e.category_slug,
                e.attendance if e.attendance else "est",
                e.exhibitors if e.exhibitors else "est",
                e.admission,
                round(b.booth_fee), b.booth_fee_estimated,
                round(b.fuel_cost), round(b.lodging_cost), round(b.meals_cost),
                e.juried, e.deadlines, e.promoter, e.url,
                "; ".join(b.notes),
            ])


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

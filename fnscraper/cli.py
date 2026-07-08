"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config, export, persist, pipeline, report, tui


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fnscraper",
        description=(
            "Find the most profitable festivals/fairs for a salsa vendor "
            "within a drive-time radius of Zanesville, OH, using "
            "festivalnet.com listings."
        ),
    )
    p.add_argument("--weeks", type=int, default=8,
                   help="How many weeks ahead to scan (default: 8)")
    p.add_argument("--states", nargs="*", default=None, metavar="STATE",
                   help="State page slugs to crawl (default: all states "
                        "within reach, e.g. Ohio West-Virginia)")
    p.add_argument("--max-drive-hours", type=float, default=config.MAX_DRIVE_HOURS,
                   help="One-way drive-time limit (default: 10)")
    p.add_argument("--top", type=int, default=5,
                   help="Events to show per weekend (default: 5)")
    p.add_argument("--output", default="reports",
                   help="Output directory (default: reports/)")
    p.add_argument("--refresh", action="store_true",
                   help="Ignore the HTTP cache and re-fetch everything")
    p.add_argument("--pick", action="store_true",
                   help="Force the interactive show picker")
    p.add_argument("--no-pick", action="store_true",
                   help="Skip the picker; print the list and write reports")
    p.add_argument("--browse", action="store_true",
                   help="Reopen the picker on the last scrape's results "
                        "without hitting the network")
    p.add_argument("--max-pages-per-state", type=int,
                   default=config.MAX_PAGES_PER_STATE, help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = config.Settings.from_env(
        weeks_ahead=args.weeks,
        max_drive_hours=args.max_drive_hours,
        top_per_weekend=args.top,
        output_dir=args.output,
        refresh=args.refresh,
        max_pages_per_state=args.max_pages_per_state,
    )
    if args.states:
        settings.states = args.states

    out_dir = Path(settings.output_dir)
    results_path = out_dir / "results.json"

    if args.browse:
        if not results_path.exists():
            print(f"No saved results at {results_path}; run a scrape first.")
            return 1
        scored = persist.load_results(results_path)
    else:
        scored = pipeline.run(settings)
        if not scored:
            print("No qualifying events found. Try --weeks or --refresh.")
            return 1
        persist.save_results(scored, results_path)
        weekends = pipeline.group_by_weekend(scored)
        export.export_csv(scored, out_dir / "all_events.csv")
        report.write_weekend_report(
            weekends, out_dir, settings.top_per_weekend, settings.max_drive_hours
        )

    # Interactive picker: on by default when attached to a real terminal.
    interactive = args.pick or (sys.stdout.isatty() and not args.no_pick)
    if interactive:
        selected = tui.run_picker(scored)
        if selected is None:
            print("Picker closed without saving.")
        elif not selected:
            print("No shows selected.")
        else:
            shortlist = report.write_shortlist(selected, out_dir)
            exported = export.export_all(selected, out_dir, "selected_shows")
            print(f"\n{len(selected)} show(s) selected:\n")
            tui.print_plain_list(selected)
            print(f"\nShortlist (readable): {shortlist}")
            print("Full-data exports (every field):")
            for p in exported:
                print(f"  {p}")
    else:
        tui.print_plain_list(scored)

    print(f"\nWeekend report: {out_dir / 'weekend_picks.md'}")
    print(f"All {len(scored)} scored events: {out_dir / 'all_events.csv'}")
    print(f"Reopen this list anytime: python -m fnscraper --browse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

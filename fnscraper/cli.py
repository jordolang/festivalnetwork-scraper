"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import (
    apps, best, config, export, importer, pdf_fill, persist, pipeline, report,
    scoring, tui,
)
from .http import Fetcher


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
                        "instantly, without hitting the network")
    p.add_argument("--jobs", "-j", type=int, default=config.DEFAULT_JOBS,
                   metavar="N",
                   help=f"Parallel page fetches (default: {config.DEFAULT_JOBS}). "
                        "Higher is faster but hits FestivalNet harder; "
                        "use 1 for the slowest, most polite crawl.")
    p.add_argument("--deadline-by", type=date.fromisoformat, metavar="YYYY-MM-DD",
                   help="Only show events with an open application deadline "
                        "on or before this date")
    p.add_argument("--max-pages-per-state", type=int,
                   default=config.MAX_PAGES_PER_STATE, help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def build_apply_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fnscraper apply",
        description=(
            "Import an exported show list (.csv/.xlsx/.md), locate each "
            "listing's promoter website, download vendor applications, and "
            "auto-fill fillable PDFs into applications/."
        ),
    )
    p.add_argument("import_file", nargs="?", default="reports/selected_shows.csv",
                   help="Exported list to import "
                        "(default: reports/selected_shows.csv)")
    p.add_argument("--out", default="applications",
                   help="Directory for downloaded/filled applications "
                        "(default: applications/)")
    p.add_argument("--limit", type=int, default=None,
                   help="Only process the first N shows")
    p.add_argument("--refresh", action="store_true",
                   help="Ignore the HTTP cache")
    p.add_argument("--no-search", action="store_true",
                   help="Don't fall back to a web search when the listing "
                        "has no public promoter website")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def build_best_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fnscraper best",
        description=(
            "One-button booking plan: the most profitable bookable shows "
            "for every weekend over the next few months, exported as a CSV "
            "the Jose Madrid Salsa admin panel can import."
        ),
    )
    p.add_argument("--months", type=int, default=config.BEST_MONTHS_AHEAD,
                   help=f"Months ahead to plan (default: {config.BEST_MONTHS_AHEAD})")
    p.add_argument("--top", type=int, default=config.BEST_TOP_PER_WEEKEND,
                   help=f"Shows per weekend (default: {config.BEST_TOP_PER_WEEKEND})")
    p.add_argument("--max-repeats", type=int, default=2,
                   help="Weekends one recurring show may occupy (default: 2)")
    p.add_argument("--out", default=config.BEST_EXPORT_DIR,
                   help=f"Export root (default: {config.BEST_EXPORT_DIR})")
    p.add_argument("--max-drive-hours", type=float, default=config.MAX_DRIVE_HOURS,
                   help="One-way drive-time limit (default: 10)")
    p.add_argument("--states", nargs="*", default=None, metavar="STATE")
    p.add_argument("--cached", action="store_true",
                   help="Plan from the last scrape's saved results instead of "
                        "hitting the network")
    p.add_argument("--refresh", action="store_true",
                   help="Ignore the HTTP cache and re-fetch everything")
    p.add_argument("--jobs", "-j", type=int, default=config.DEFAULT_JOBS, metavar="N")
    p.add_argument("--json", action="store_true",
                   help="Print a machine-readable summary on stdout (for the "
                        "website's export button)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def best_main(argv: list[str]) -> int:
    args = build_best_parser().parse_args(argv)
    # Logs go to stderr so --json keeps stdout clean for the caller.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    results_path = Path("reports") / "results.json"
    if args.cached:
        if not results_path.exists():
            print(f"No saved results at {results_path}; run without --cached "
                  "first.", file=sys.stderr)
            return 1
        # Re-score rather than replay the saved breakdowns: a breakdown is a
        # pure function of the event, so anything tuned in config.py since
        # the scrape (prices, capture rate, fee tiers) takes effect here
        # without a re-crawl.
        scored = [
            scoring.score_event(s.event)
            for s in persist.load_results(results_path)
        ]
        scored.sort(key=lambda s: s.breakdown.score, reverse=True)
    else:
        # Crawl a little past the horizon so the last weekend is fully covered.
        settings = config.Settings.from_env(
            weeks_ahead=args.months * 5,
            max_drive_hours=args.max_drive_hours,
            refresh=args.refresh,
            jobs=args.jobs,
        )
        if args.states:
            settings.states = args.states
        scored = pipeline.run(settings)
        if not scored:
            print("No qualifying events found.", file=sys.stderr)
            return 1
        persist.save_results(scored, results_path)

    plan = best.build_plan(
        scored, months=args.months, top=args.top, max_repeats=args.max_repeats
    )
    if not plan:
        print("No bookable weekend shows in the window.", file=sys.stderr)
        return 1
    csv_path = best.export_plan(plan, base_dir=args.out)

    weekends = sorted({s.weekend for s in plan})
    if args.json:
        import json
        print(json.dumps({
            "csv": str(csv_path),
            "spec": str(csv_path.parent / "SPEC.md"),
            "shows": len(plan),
            "weekends": len(weekends),
            "first_weekend": weekends[0].isoformat(),
            "last_weekend": weekends[-1].isoformat(),
            "columns": best.COLUMNS,
        }))
        return 0

    print(f"\n{len(plan)} shows across {len(weekends)} weekends "
          f"({weekends[0]:%b %d} - {weekends[-1]:%b %d, %Y})\n")
    for weekend in weekends:
        rows = [s for s in plan if s.weekend == weekend]
        print(f"  Weekend of {weekend:%b %d}")
        for slot in rows:
            e, b = slot.scored.event, slot.scored.breakdown
            print(f"    ${b.est_profit:>8,.0f} profit  "
                  f"{best.drive_time(e.drive_hours):>8}  "
                  f"{e.city}, {e.state}  {e.name[:44]}")
    print(f"\nCSV:  {csv_path}")
    print(f"Spec: {csv_path.parent / 'SPEC.md'}")
    return 0


def apply_main(argv: list[str]) -> int:
    args = build_apply_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        shows = importer.load_shows(args.import_file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot import {args.import_file}: {exc}")
        print("Export a selection first (run the picker), or pass a path to "
              "a selected_shows .csv/.xlsx/.md file.")
        return 1
    if args.limit:
        shows = shows[: args.limit]

    pdf_fill.write_example_profile(".")
    profile, is_real = pdf_fill.load_profile(".")

    settings = config.Settings.from_env(refresh=args.refresh)
    fetcher = Fetcher(cache_dir=settings.cache_dir, refresh=args.refresh)
    if settings.username and settings.password:
        fetcher.login(settings.username, settings.password)

    hunter = apps.ApplicationHunter(
        fetcher, out_dir=args.out, profile=profile, profile_is_real=is_real,
        search_fallback=not args.no_search,
    )
    results = hunter.run(shows)

    print(f"\nProcessed {len(results)} show(s):")
    for r in results:
        bits = []
        if r.filled:
            bits.append(f"{len(r.filled)} PDF(s) auto-filled")
        if r.downloaded:
            bits.append(f"{len(r.downloaded)} downloaded")
        if r.online_forms:
            bits.append(f"{len(r.online_forms)} online form(s) to fill in browser")
        if not bits:
            bits.append("no application found — check the listing")
        print(f"  {r.name}: " + ", ".join(bits))
    print(f"\nEverything saved under {args.out}/ — see {args.out}/INDEX.md")
    if not is_real:
        print("NOTE: filled with placeholder data. Copy "
              "vendor_profile.example.json to vendor_profile.json, edit it, "
              "and re-run.")
    print("Review every auto-filled PDF before sending it to a promoter.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv[:1] == ["apply"]:
        return apply_main(argv[1:])
    if argv[:1] == ["best"]:
        return best_main(argv[1:])
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
        jobs=args.jobs,
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

    if args.deadline_by:
        scored = tui.filter_by_deadline(scored, args.deadline_by)
        if not scored:
            print(f"No events have an open application deadline on or before "
                  f"{args.deadline_by}.")
            return 0

    if not args.browse:
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

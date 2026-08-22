"""The FestivalNet Scraper desktop app.

``python -m fnscraper.gui`` (or ``python -m fnscraper gui``) opens the
window.  Everything here is optional: the package imports without Tk
installed, and :func:`launch` says so plainly instead of raising an
ImportError out of a double-clicked icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["available", "launch", "main"]

MISSING_TK = (
    "This build of Python has no Tk support, so the desktop window cannot "
    "open.\n"
    "  Windows/macOS: install Python from python.org, which bundles Tk.\n"
    "  Debian/Ubuntu: sudo apt install python3-tk\n"
    "  Fedora:        sudo dnf install python3-tkinter\n"
    "The command-line scraper still works: python -m fnscraper --help"
)


def available() -> bool:
    """True when Tk can be imported in this interpreter."""
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def launch(sample: bool = False, results_file: Path | None = None) -> int:
    if not available():
        print(MISSING_TK, file=sys.stderr)
        return 2
    from .app import ScraperWindow

    window = ScraperWindow(sample=sample, results_file=results_file)
    window.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="fnscraper-gui",
        description="Open the FestivalNet Scraper desktop window.",
    )
    parser.add_argument("--sample", action="store_true",
                        help="start with a demo result set loaded")
    parser.add_argument("--open", metavar="RESULTS.JSON", type=Path,
                        help="open a saved results file on startup")
    args = parser.parse_args(argv)
    return launch(sample=args.sample, results_file=args.open)

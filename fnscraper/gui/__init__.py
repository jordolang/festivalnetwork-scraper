"""The FestivalNet Scraper desktop app.

``python -m fnscraper.gui`` (or ``python -m fnscraper gui``) opens the
window.  Everything here is optional: the package imports without Tk
installed, and :func:`launch` says so plainly instead of raising an
ImportError out of a double-clicked icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["available", "launch", "main", "selftest"]

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


def selftest() -> int:
    """Prove a *frozen* build is sound, without needing a display.

    The failures that only appear after packaging are missing modules and
    missing data files — a hidden import PyInstaller did not trace, or an
    icon that never made it into the bundle.  Both are caught by importing
    the whole window and resolving the assets, so this runs on a CI runner
    with no desktop session.  Creating a Tk root is attempted too, and a
    missing display is reported without failing: that is the runner's
    property, not the build's.
    """
    import tkinter

    from . import app, detail, grid, icons, panels, paths, theme, viewmodel
    from .. import export, persist, pipeline          # noqa: F401

    problems: list[str] = []
    if not hasattr(app, "ScraperWindow"):
        problems.append("fnscraper.gui.app has no ScraperWindow")
    for module in (detail, grid, icons, panels, theme, viewmodel):
        print(f"  imported {module.__name__}")

    icon = paths.resource_dir() / "assets" / "icons" / "festivalnet-256.png"
    if icon.is_file():
        print(f"  found {icon}")
    else:
        problems.append(f"bundled icon missing: {icon}")

    try:
        root = tkinter.Tk()
        root.destroy()
        print(f"  Tk {tkinter.TkVersion} opened a window")
    except tkinter.TclError as exc:
        print(f"  Tk {tkinter.TkVersion} present, no display here ({exc})")

    for problem in problems:
        print(f"  PROBLEM: {problem}", file=sys.stderr)
    print("self-test failed" if problems else "self-test passed")
    return 1 if problems else 0


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
    parser.add_argument("--check", action="store_true",
                        help="verify this build can start, then exit "
                             "(used by CI against the packaged app)")
    args = parser.parse_args(argv)
    if args.check:
        if not available():
            print(MISSING_TK, file=sys.stderr)
            return 1
        return selftest()
    return launch(sample=args.sample, results_file=args.open)

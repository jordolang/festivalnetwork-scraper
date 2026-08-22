"""Entry point for the packaged desktop app.

PyInstaller needs a real script to freeze, and a frozen GUI app needs two
things a module entry point does not do for it: multiprocessing's frozen
guard, and a place to show a startup failure that is not a terminal the
user does not have.
"""

from __future__ import annotations

import multiprocessing
import sys
import traceback


def main() -> int:
    multiprocessing.freeze_support()
    try:
        from fnscraper.gui import main as gui_main
        return gui_main(sys.argv[1:])
    except Exception:                      # noqa: BLE001 - last-ditch reporter
        details = traceback.format_exc()
        sys.stderr.write(details)
        try:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror(
                "FestivalNet Scraper",
                "The app could not start.\n\n" + details[-1500:],
            )
        except Exception:                  # noqa: BLE001 - nothing left to try
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

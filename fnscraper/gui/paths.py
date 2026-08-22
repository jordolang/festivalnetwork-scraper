"""Where the desktop app keeps its files.

The command line writes into the working directory, which is right for a
terminal session.  A double-clicked app has no meaningful working
directory — on macOS it is ``/`` and the bundle itself is read-only — so
the window puts documents where the platform expects them and keeps its
caches out of the way.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FestivalNet Scraper"
APP_SLUG = "fnscraper"


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def config_dir() -> Path:
    """Where window settings live."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or _home() / "AppData/Roaming")
        return base / APP_NAME
    if sys.platform == "darwin":
        return _home() / "Library/Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")
    return base / APP_SLUG


def cache_dir() -> Path:
    """Where fetched pages and the geocode cache live."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or _home() / "AppData/Local")
        return base / APP_NAME / "cache"
    if sys.platform == "darwin":
        return _home() / "Library/Caches" / APP_NAME
    base = Path(os.environ.get("XDG_CACHE_HOME") or _home() / ".cache")
    return base / APP_SLUG


def documents_dir() -> Path:
    candidate = _home() / "Documents"
    return candidate if candidate.is_dir() else _home()


def default_output_dir() -> Path:
    """Where exports and the saved results file go by default.

    A checkout being developed in keeps its own ``reports/`` folder, so a
    developer's exports land next to the code they are testing; an
    installed app writes to Documents.
    """
    if is_frozen():
        return documents_dir() / APP_NAME
    return Path.cwd() / "reports"


def is_frozen() -> bool:
    """True inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Where bundled read-only assets (icons) ended up."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent.parent


def settings_file() -> Path:
    return config_dir() / "window-settings.json"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

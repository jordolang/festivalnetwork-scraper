"""Colours, fonts and ttk styling for the desktop app.

Everything visual lives here so the palette can be retuned in one place.
The app is dark by design — the same charcoal/blue/green scheme on
Windows, macOS and Linux — because a scraper's results table is read for
long stretches and a light theme in a dim room is punishing.

Only three ttk widgets survive into the app (Scrollbar, Combobox, Entry);
the rest are hand-drawn in :mod:`fnscraper.gui.widgets` because ttk's
native macOS theme silently ignores background colours, which would leave
half the window light grey on a Mac.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --- surfaces --------------------------------------------------------------
BG = "#1e1e1e"            # main content background
BG_SIDEBAR = "#1a1a1a"    # settings rail
BG_BAR = "#202020"        # toolbars and the status bar
BG_CARD = "#242426"       # stat cards, panels
BG_CARD_HI = "#2a2a2d"    # a card being pointed at / highlighted
BG_HEADER = "#232325"     # table header row
BG_ROW_ALT = "#212123"    # zebra striping
BG_ROW_HOVER = "#2a2a2e"
BG_ROW_SELECTED = "#2d3a4a"
BG_INPUT = "#1c1c1e"
BG_BUTTON = "#2b2b2e"
BG_BUTTON_HOVER = "#37373b"
BG_POPUP = "#2a2a2d"

# --- lines -----------------------------------------------------------------
BORDER = "#323236"
BORDER_SOFT = "#2a2a2c"
BORDER_FOCUS = "#4a4a52"

# --- text ------------------------------------------------------------------
FG = "#e8e8ea"
FG_MUTED = "#9c9ca4"
FG_DIM = "#6d6d75"
FG_HEADING = "#c9c9d1"

# --- accents ---------------------------------------------------------------
ACCENT = "#2f80ed"        # checkbox fill, active tab underline
ACCENT_TEXT = "#4aa3ff"   # links
GREEN = "#5ed49a"         # scores, revenue
GREEN_DIM = "#3f9d73"
RED = "#f26b6b"           # failures, losses
AMBER = "#e2b341"
PURPLE = "#a78bfa"
DISABLED = "#4a4a50"

# Card accent colours, in the order the overview lays them out.
CARD_ACCENTS = (ACCENT_TEXT, GREEN, AMBER, GREEN, PURPLE, ACCENT_TEXT)

# Font stacks, best first.  Whichever is actually installed wins.
_UI_FAMILIES = (
    "Segoe UI Variable Text", "Segoe UI",          # Windows
    "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",   # macOS
    "Inter", "Noto Sans", "DejaVu Sans", "Liberation Sans",  # Linux
)
_MONO_FAMILIES = (
    "Cascadia Mono", "Consolas", "SF Mono", "Menlo",
    "DejaVu Sans Mono", "Liberation Mono", "Courier New",
)

# Filled in by init(); the module-level names are what widgets reference.
UI = ("TkDefaultFont", 10)
UI_SMALL = ("TkDefaultFont", 9)
UI_TINY = ("TkDefaultFont", 8)
UI_BOLD = ("TkDefaultFont", 10, "bold")
UI_SMALL_BOLD = ("TkDefaultFont", 9, "bold")
UI_TINY_BOLD = ("TkDefaultFont", 8, "bold")
UI_TITLE = ("TkDefaultFont", 13, "bold")
UI_HUGE = ("TkDefaultFont", 20, "bold")
UI_BIG = ("TkDefaultFont", 15, "bold")
MONO = ("TkFixedFont", 9)


def _first_installed(root: tk.Misc, families: tuple[str, ...], fallback: str) -> str:
    available = {name.lower() for name in tkfont.families(root)}
    for family in families:
        if family.lower() in available:
            return family
    return fallback


def init(root: tk.Misc) -> None:
    """Resolve the font stacks and install the ttk styles.

    Call once, right after the root window exists — font enumeration needs
    a live interpreter.
    """
    global UI, UI_SMALL, UI_TINY, UI_BOLD, UI_SMALL_BOLD, UI_TINY_BOLD
    global UI_TITLE, UI_HUGE, UI_BIG, MONO

    ui = _first_installed(root, _UI_FAMILIES, "TkDefaultFont")
    mono = _first_installed(root, _MONO_FAMILIES, "TkFixedFont")
    # Windows and Linux measure UI text a point smaller than macOS does;
    # without the bump the Mac window looks like a scaled-up mockup.
    base = 12 if root.tk.call("tk", "windowingsystem") == "aqua" else 10

    UI = (ui, base)
    UI_SMALL = (ui, base - 1)
    UI_TINY = (ui, base - 2)
    UI_BOLD = (ui, base, "bold")
    UI_SMALL_BOLD = (ui, base - 1, "bold")
    UI_TINY_BOLD = (ui, base - 2, "bold")
    UI_TITLE = (ui, base + 3, "bold")
    UI_BIG = (ui, base + 5, "bold")
    UI_HUGE = (ui, base + 10, "bold")
    MONO = (mono, base - 1)

    # Tk's own defaults leak into menus, dialogs and the odd stray widget.
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=ui, size=base)
        except tk.TclError:      # pragma: no cover - font missing on this box
            pass

    _init_ttk(root)


def _init_ttk(root: tk.Misc) -> None:
    style = ttk.Style(root)
    # 'clam' is the only built-in theme that honours colour options on all
    # three platforms; the native themes draw from the OS and ignore us.
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(
        "Dark.Vertical.TScrollbar",
        troughcolor=BG, background="#3a3a3f", bordercolor=BG,
        arrowcolor=FG_DIM, darkcolor="#3a3a3f", lightcolor="#3a3a3f",
        gripcount=0, relief="flat", arrowsize=12, width=11,
    )
    style.map(
        "Dark.Vertical.TScrollbar",
        background=[("active", "#4d4d54"), ("pressed", "#5a5a62")],
    )
    style.configure(
        "Dark.Horizontal.TScrollbar",
        troughcolor=BG, background="#3a3a3f", bordercolor=BG,
        arrowcolor=FG_DIM, darkcolor="#3a3a3f", lightcolor="#3a3a3f",
        gripcount=0, relief="flat", arrowsize=12, width=11,
    )
    style.map(
        "Dark.Horizontal.TScrollbar",
        background=[("active", "#4d4d54"), ("pressed", "#5a5a62")],
    )


def scrollbar(parent: tk.Misc, orient: str = "vertical", **kw) -> ttk.Scrollbar:
    """A thin dark scrollbar."""
    name = "Dark.Vertical.TScrollbar" if orient == "vertical" \
        else "Dark.Horizontal.TScrollbar"
    return ttk.Scrollbar(parent, orient=orient, style=name, **kw)

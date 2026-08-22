"""Vector icons drawn straight onto a Tk canvas.

Tk has no icon font and bundling PNGs would mean shipping (and scaling)
bitmaps for every display density, so each icon is a handful of canvas
items described in a 0..1 unit box.  They stay crisp at any size and cost
nothing to recolour, which the toolbar needs for its hover states.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

Painter = Callable[[tk.Canvas, float, float, float, str, float], list[int]]

_PAINTERS: dict[str, Painter] = {}


def icon(name: str):
    def register(fn: Painter) -> Painter:
        _PAINTERS[name] = fn
        return fn
    return register


def names() -> list[str]:
    return sorted(_PAINTERS)


def draw(canvas: tk.Canvas, name: str, x: float, y: float, size: float,
         color: str, width: float = 1.6, tags: str = "icon") -> list[int]:
    """Paint ``name`` with its top-left corner at (x, y).  Returns item ids."""
    painter = _PAINTERS.get(name)
    if painter is None:
        return []
    items = painter(canvas, x, y, size, color, width)
    for item in items:
        canvas.addtag_withtag(tags, item)
    return items


# --- helpers ---------------------------------------------------------------

def _line(c, x, y, s, color, w, *points, **kw):
    coords = []
    for i in range(0, len(points), 2):
        coords += [x + points[i] * s, y + points[i + 1] * s]
    kw.setdefault("capstyle", "round")
    kw.setdefault("joinstyle", "round")
    return c.create_line(*coords, fill=color, width=w, **kw)


def _rect(c, x, y, s, color, w, x0, y0, x1, y1, fill=""):
    return c.create_rectangle(
        x + x0 * s, y + y0 * s, x + x1 * s, y + y1 * s,
        outline=color, width=w, fill=fill,
    )


def _oval(c, x, y, s, color, w, cx, cy, r, fill=""):
    return c.create_oval(
        x + (cx - r) * s, y + (cy - r) * s, x + (cx + r) * s, y + (cy + r) * s,
        outline=color, width=w, fill=fill,
    )


def _poly(c, x, y, s, color, w, *points, fill=None, outline=""):
    coords = []
    for i in range(0, len(points), 2):
        coords += [x + points[i] * s, y + points[i + 1] * s]
    return c.create_polygon(
        *coords, fill=color if fill is None else fill,
        outline=outline, width=w if outline else 0,
    )


# --- toolbar ---------------------------------------------------------------

@icon("play")
def _play(c, x, y, s, color, w):
    return [_poly(c, x, y, s, color, w, 0.24, 0.14, 0.86, 0.5, 0.24, 0.86)]


@icon("stop")
def _stop(c, x, y, s, color, w):
    return [_rect(c, x, y, s, color, 0, 0.22, 0.22, 0.78, 0.78, fill=color)]


@icon("export")
def _export(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.5, 0.72, 0.5, 0.18),
        _line(c, x, y, s, color, w, 0.28, 0.38, 0.5, 0.16, 0.72, 0.38),
        _line(c, x, y, s, color, w, 0.16, 0.62, 0.16, 0.86, 0.84, 0.86, 0.84, 0.62),
    ]


@icon("folder")
def _folder(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w,
              0.12, 0.80, 0.12, 0.22, 0.42, 0.22, 0.52, 0.36, 0.88, 0.36,
              0.88, 0.80, 0.12, 0.80),
    ]


@icon("save")
def _save(c, x, y, s, color, w):
    return [
        _rect(c, x, y, s, color, w, 0.16, 0.16, 0.84, 0.84),
        _rect(c, x, y, s, color, w, 0.34, 0.16, 0.66, 0.42),
        _rect(c, x, y, s, color, w, 0.30, 0.58, 0.70, 0.84),
    ]


@icon("load")
def _load(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.5, 0.16, 0.5, 0.70),
        _line(c, x, y, s, color, w, 0.28, 0.48, 0.5, 0.72, 0.72, 0.48),
        _line(c, x, y, s, color, w, 0.16, 0.86, 0.84, 0.86),
    ]


@icon("refresh")
def _refresh(c, x, y, s, color, w):
    return [
        c.create_arc(x + 0.16 * s, y + 0.16 * s, x + 0.84 * s, y + 0.84 * s,
                     start=40, extent=280, style="arc", outline=color, width=w),
        _poly(c, x, y, s, color, w, 0.70, 0.06, 0.92, 0.30, 0.60, 0.32),
    ]


@icon("search")
def _search(c, x, y, s, color, w):
    return [
        _oval(c, x, y, s, color, w, 0.44, 0.44, 0.27),
        _line(c, x, y, s, color, w, 0.64, 0.64, 0.86, 0.86),
    ]


@icon("columns")
def _columns(c, x, y, s, color, w):
    return [
        _rect(c, x, y, s, color, w, 0.14, 0.20, 0.86, 0.80),
        _line(c, x, y, s, color, w, 0.38, 0.20, 0.38, 0.80),
        _line(c, x, y, s, color, w, 0.62, 0.20, 0.62, 0.80),
    ]


@icon("link")
def _link(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.42, 0.58, 0.58, 0.42),
        _line(c, x, y, s, color, w, 0.34, 0.66, 0.22, 0.78, 0.22, 0.90),
        _line(c, x, y, s, color, w, 0.66, 0.34, 0.78, 0.22, 0.90, 0.22),
    ]


# --- chevrons and pager arrows --------------------------------------------

@icon("chevron-down")
def _chevron_down(c, x, y, s, color, w):
    return [_line(c, x, y, s, color, w, 0.24, 0.40, 0.5, 0.64, 0.76, 0.40)]


@icon("chevron-up")
def _chevron_up(c, x, y, s, color, w):
    return [_line(c, x, y, s, color, w, 0.24, 0.62, 0.5, 0.38, 0.76, 0.62)]


@icon("chevron-left")
def _chevron_left(c, x, y, s, color, w):
    return [_line(c, x, y, s, color, w, 0.60, 0.24, 0.36, 0.5, 0.60, 0.76)]


@icon("chevron-right")
def _chevron_right(c, x, y, s, color, w):
    return [_line(c, x, y, s, color, w, 0.40, 0.24, 0.64, 0.5, 0.40, 0.76)]


@icon("first")
def _first(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.70, 0.24, 0.46, 0.5, 0.70, 0.76),
        _line(c, x, y, s, color, w, 0.32, 0.24, 0.32, 0.76),
    ]


@icon("last")
def _last(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.30, 0.24, 0.54, 0.5, 0.30, 0.76),
        _line(c, x, y, s, color, w, 0.68, 0.24, 0.68, 0.76),
    ]


@icon("check")
def _check(c, x, y, s, color, w):
    return [_line(c, x, y, s, color, w, 0.22, 0.52, 0.42, 0.72, 0.78, 0.30)]


@icon("close")
def _close(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.26, 0.26, 0.74, 0.74),
        _line(c, x, y, s, color, w, 0.74, 0.26, 0.26, 0.74),
    ]


# --- stat-card glyphs ------------------------------------------------------

@icon("calendar")
def _calendar(c, x, y, s, color, w):
    return [
        _rect(c, x, y, s, color, w, 0.14, 0.22, 0.86, 0.86),
        _line(c, x, y, s, color, w, 0.14, 0.40, 0.86, 0.40),
        _line(c, x, y, s, color, w, 0.32, 0.12, 0.32, 0.30),
        _line(c, x, y, s, color, w, 0.68, 0.12, 0.68, 0.30),
    ]


@icon("globe")
def _globe(c, x, y, s, color, w):
    return [
        _oval(c, x, y, s, color, w, 0.5, 0.5, 0.36),
        _oval(c, x, y, s, color, w, 0.5, 0.5, 0.16),
        _line(c, x, y, s, color, w, 0.14, 0.5, 0.86, 0.5),
    ]


@icon("building")
def _building(c, x, y, s, color, w):
    items = [
        _rect(c, x, y, s, color, w, 0.16, 0.28, 0.52, 0.86),
        _rect(c, x, y, s, color, w, 0.56, 0.46, 0.86, 0.86),
    ]
    for row in (0.40, 0.56, 0.72):
        items.append(_line(c, x, y, s, color, max(1.0, w * 0.7),
                           0.24, row, 0.44, row))
    return items


@icon("dollar")
def _dollar(c, x, y, s, color, w):
    return [
        _oval(c, x, y, s, color, w, 0.5, 0.5, 0.38),
        _line(c, x, y, s, color, w, 0.5, 0.22, 0.5, 0.78),
        _line(c, x, y, s, color, w,
              0.64, 0.36, 0.44, 0.36, 0.38, 0.44, 0.44, 0.50, 0.58, 0.50,
              0.64, 0.56, 0.58, 0.64, 0.36, 0.64),
    ]


@icon("chart")
def _chart(c, x, y, s, color, w):
    bars = [(0.20, 0.62), (0.42, 0.44), (0.64, 0.26)]
    items = [_line(c, x, y, s, color, w, 0.14, 0.86, 0.88, 0.86)]
    for x0, top in bars:
        items.append(_rect(c, x, y, s, color, w, x0, top, x0 + 0.16, 0.84))
    return items


@icon("people")
def _people(c, x, y, s, color, w):
    return [
        _oval(c, x, y, s, color, w, 0.38, 0.34, 0.16),
        c.create_arc(x + 0.12 * s, y + 0.52 * s, x + 0.64 * s, y + 1.02 * s,
                     start=0, extent=180, style="arc", outline=color, width=w),
        _oval(c, x, y, s, color, w, 0.72, 0.38, 0.12),
        c.create_arc(x + 0.54 * s, y + 0.56 * s, x + 0.94 * s, y + 0.98 * s,
                     start=0, extent=180, style="arc", outline=color, width=w),
    ]


@icon("map")
def _map(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w,
              0.12, 0.26, 0.38, 0.16, 0.62, 0.30, 0.88, 0.20, 0.88, 0.76,
              0.62, 0.86, 0.38, 0.72, 0.12, 0.82, 0.12, 0.26),
        _line(c, x, y, s, color, max(1.0, w * 0.8), 0.38, 0.16, 0.38, 0.72),
        _line(c, x, y, s, color, max(1.0, w * 0.8), 0.62, 0.30, 0.62, 0.86),
    ]


@icon("pin")
def _pin(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w,
              0.5, 0.90, 0.24, 0.50, 0.28, 0.24, 0.5, 0.12, 0.72, 0.24,
              0.76, 0.50, 0.5, 0.90),
        _oval(c, x, y, s, color, w, 0.5, 0.40, 0.11),
    ]


@icon("clock")
def _clock(c, x, y, s, color, w):
    return [
        _oval(c, x, y, s, color, w, 0.5, 0.5, 0.36),
        _line(c, x, y, s, color, w, 0.5, 0.28, 0.5, 0.52, 0.68, 0.62),
    ]


@icon("warning")
def _warning(c, x, y, s, color, w):
    return [
        _line(c, x, y, s, color, w, 0.5, 0.12, 0.92, 0.86, 0.08, 0.86, 0.5, 0.12),
        _line(c, x, y, s, color, w, 0.5, 0.40, 0.5, 0.62),
        _line(c, x, y, s, color, w, 0.5, 0.74, 0.5, 0.75),
    ]


@icon("logo")
def _logo(c, x, y, s, color, w):
    """The app mark: a magnifier over a ticket stub."""
    return [
        _oval(c, x, y, s, color, w, 0.5, 0.5, 0.46, fill=color),
        _oval(c, x, y, s, "#101014", w, 0.44, 0.44, 0.22),
        _line(c, x, y, s, "#101014", w * 1.4, 0.60, 0.60, 0.78, 0.78),
    ]

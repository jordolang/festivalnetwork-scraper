"""The results table.

Drawn on a canvas rather than built from ``ttk.Treeview`` for one reason
that matters and one that helps: a Treeview cannot colour a single cell
(the score columns are green, a negative profit is red), and its native
macOS styling ignores background colours entirely, which would leave a
light-grey table in the middle of a dark window.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Sequence

from . import theme as t
from .widgets import bind_wheel
from .viewmodel import COLUMN_BY_KEY, Row, column_title

ROW_HEIGHT = 32
MEASURE_CACHE_LIMIT = 20_000
HEADER_HEIGHT = 52
CELL_PAD = 10


class DataGrid(tk.Frame):
    """A sortable, scrollable, single-selection table of :class:`Row`."""

    def __init__(self, parent: tk.Misc, columns: Sequence[str], *,
                 on_select: Callable[[Row | None], None] | None = None,
                 on_activate: Callable[[Row], None] | None = None,
                 on_sort: Callable[[str, bool], None] | None = None,
                 empty_text: str = "No results yet.", **kw):
        super().__init__(parent, bg=t.BG, **kw)
        self.columns = list(columns)
        self.rows: list[Row] = []
        self.on_select = on_select
        self.on_activate = on_activate
        self.on_sort = on_sort
        self.empty_text = empty_text
        self.sort_column: str | None = None
        self.sort_descending = True
        self.selected_key: str | None = None
        self._hover_index: int | None = None
        self._row_items: list[dict] = []
        self._widths: list[float] = []

        self.header = tk.Canvas(self, bg=t.BG_HEADER, highlightthickness=0,
                                bd=0, height=HEADER_HEIGHT, takefocus=0)
        self.header.pack(fill="x", side="top")
        body = tk.Frame(self, bg=t.BG)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=t.BG, highlightthickness=0, bd=0,
                                takefocus=1)
        self.vbar = t.scrollbar(body, "vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.hbar = t.scrollbar(self, "horizontal", command=self._xview)
        self.canvas.configure(xscrollcommand=self._on_xscroll)

        self._body_font = None
        self._bold_font = None
        # Text widths, per font.  Every ``Font.measure`` is a round trip
        # into Tk (and, on macOS, into Core Text), and a redraw used to
        # make hundreds of them for strings it had measured the last time
        # round — header words, the same "$1,250" fee, a name being elided
        # one character at a time.  That was most of the cost of a keystroke.
        self._widths_cache: dict[tuple[int, str], float] = {}
        # Packing a scrollbar resizes the canvas, which fires <Configure>,
        # which redraws and re-evaluates the scrollbar.  Remember what is
        # already on screen so that loop settles after one pass.
        self._hbar_shown = False
        self._vbar_shown = False

        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.header.bind("<Button-1>", self._on_header_click)
        self.header.bind("<Motion>", self._on_header_motion)
        bind_wheel(self.canvas, lambda step: self.canvas.yview_scroll(step, "units"))

    # -- fonts ---------------------------------------------------------
    def _fonts(self):
        if self._body_font is None:
            self._body_font = tkfont.Font(font=t.UI_SMALL)
            self._bold_font = tkfont.Font(font=t.UI_SMALL_BOLD)
        return self._body_font, self._bold_font

    def _measure(self, font, text: str) -> float:
        key = (id(font), text)
        width = self._widths_cache.get(key)
        if width is None:
            if len(self._widths_cache) >= MEASURE_CACHE_LIMIT:
                self._widths_cache.clear()
            width = self._widths_cache[key] = font.measure(text)
        return width

    # -- data ----------------------------------------------------------
    def set_columns(self, columns: Sequence[str]):
        self.columns = list(columns)
        self.redraw()

    def set_rows(self, rows: Sequence[Row], keep_selection: bool = True):
        self.rows = list(rows)
        if not keep_selection or not any(r.key == self.selected_key for r in self.rows):
            self.selected_key = None
        self.canvas.yview_moveto(0)
        self.redraw()

    def selected_row(self) -> Row | None:
        for row in self.rows:
            if row.key == self.selected_key:
                return row
        return None

    def select_key(self, key: str | None, notify: bool = True):
        self.selected_key = key
        self._paint_backgrounds()
        if notify and self.on_select:
            self.on_select(self.selected_row())

    # -- scrolling -----------------------------------------------------
    def _xview(self, *args):
        self.canvas.xview(*args)
        self.header.xview(*args)

    def _on_xscroll(self, first: str, last: str):
        wanted = not (float(first) <= 0.0 and float(last) >= 1.0)
        if wanted != self._hbar_shown:
            self._hbar_shown = wanted
            if wanted:
                self.hbar.pack(fill="x", side="bottom")
            else:
                self.hbar.pack_forget()
        self.hbar.set(first, last)
        self.header.xview_moveto(float(first))

    def _on_yscroll(self, first: str, last: str):
        wanted = not (float(first) <= 0.0 and float(last) >= 1.0)
        if wanted != self._vbar_shown:
            self._vbar_shown = wanted
            if wanted:
                self.vbar.pack(side="right", fill="y")
            else:
                self.vbar.pack_forget()
        self.vbar.set(first, last)

    # -- layout --------------------------------------------------------
    def _min_width(self, key: str) -> float:
        """Narrowest this column may get.

        Two floors apply.  The heading's widest word, because squeezing
        past that makes Tk wrap it mid-word — the "Attendanc / e" a naive
        proportional shrink produces.  And, for number columns, their
        widest cell: "$17,098" needs exactly one width and eliding it to
        "$17,0…" destroys the value, whereas a clipped festival name is
        still recognisable.
        """
        body, bold = self._fonts()
        longest = max((self._measure(bold, word)
                       for word in column_title(key).split()), default=40)
        if COLUMN_BY_KEY[key].numeric and self.rows:
            longest = max(longest, max(self._measure(body, row.text(key))
                                       for row in self.rows))
        return longest + 2 * CELL_PAD + 6

    def _layout(self) -> list[float]:
        """Column widths: stretched when there is room, squeezed when not."""
        specs = [COLUMN_BY_KEY[key] for key in self.columns]
        widths = [float(spec.width) for spec in specs]
        # One pixel of headroom: a layout that lands exactly on the
        # viewport width still trips Tk's scroll range and flashes a
        # horizontal scrollbar under the table.
        available = self.canvas.winfo_width() - 1
        if available <= 40:
            return widths
        total = sum(widths)

        if total < available:
            # Give the slack to the text columns; numbers look wrong when
            # their right edge drifts away from the values.
            stretchy = [i for i, spec in enumerate(specs) if not spec.numeric]
            targets = stretchy or list(range(len(widths)))
            share = (available - total) / len(targets)
            for i in targets:
                widths[i] += share
            return widths

        # Too wide: shave columns down to their minimums before falling back
        # to a horizontal scrollbar, so the common case of "one column too
        # many" still shows the whole table.  Numbers give up their slack
        # first — "$17,098" needs a fixed amount of room and no more, while
        # a truncated festival name is the one cell nobody can read around.
        minimums = [self._min_width(key) for key in self.columns]
        if sum(minimums) >= available:
            return widths
        deficit = total - available
        for numeric_pass in (True, False):
            slack = sum(width - minimum
                        for width, minimum, spec in zip(widths, minimums, specs)
                        if spec.numeric is numeric_pass)
            if slack <= 0:
                continue
            take = min(deficit, slack)
            for i, spec in enumerate(specs):
                if spec.numeric is numeric_pass:
                    widths[i] -= (widths[i] - minimums[i]) * take / slack
            deficit -= take
            if deficit <= 0.5:
                break
        return widths

    def _elide(self, text: str, font, width: float) -> str:
        if self._measure(font, text) <= width:
            return text
        # The longest prefix that fits with an ellipsis, found by bisection:
        # a handful of measurements instead of one per character dropped.
        ellipsis = "…"
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self._measure(font, text[:middle] + ellipsis) <= width:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip() + ellipsis

    # -- painting ------------------------------------------------------
    def redraw(self):
        body_font, bold_font = self._fonts()
        self.header.delete("all")
        self.canvas.delete("all")
        self._row_items = []

        widths = self._layout()
        self._widths = widths
        total_width = sum(widths)

        # header
        x = 0.0
        for key, width in zip(self.columns, widths):
            spec = COLUMN_BY_KEY[key]
            anchor, tx = _anchor_for(spec.anchor, x, width)
            arrow_room = 14 if key == self.sort_column else 0
            self.header.create_text(
                tx - (arrow_room if spec.anchor == "e" else 0),
                HEADER_HEIGHT / 2, text=column_title(key), fill=t.FG_HEADING,
                font=bold_font, anchor=anchor,
                width=max(20, width - 2 * CELL_PAD - arrow_room),
            )
            if key == self.sort_column:
                self._draw_sort_arrow(tx, spec.anchor, width, x)
            x += width
        self.header.create_line(
            0, HEADER_HEIGHT - 1,
            max(total_width, self.header.winfo_width()), HEADER_HEIGHT - 1,
            fill=t.BORDER)
        self.header.configure(scrollregion=(0, 0, total_width, HEADER_HEIGHT))

        if not self.rows:
            self.canvas.create_text(
                max(total_width, self.canvas.winfo_width()) / 2, 60,
                text=self.empty_text, fill=t.FG_DIM, font=t.UI_SMALL,
            )
            self.canvas.configure(scrollregion=(0, 0, total_width, 120))
            return

        wide = max(total_width, self.canvas.winfo_width())
        for index, row in enumerate(self.rows):
            top = index * ROW_HEIGHT
            background = self.canvas.create_rectangle(
                0, top, wide, top + ROW_HEIGHT,
                fill=self._row_bg(index, row), outline="",
            )
            self.canvas.create_line(0, top + ROW_HEIGHT - 1, wide,
                                    top + ROW_HEIGHT - 1, fill=t.BORDER_SOFT)
            texts = []
            x = 0.0
            for key, width in zip(self.columns, widths):
                spec = COLUMN_BY_KEY[key]
                anchor, tx = _anchor_for(spec.anchor, x, width)
                font = bold_font if key in ("overall", "profit_index") else body_font
                label = self._elide(row.text(key), font, width - 2 * CELL_PAD)
                texts.append(self.canvas.create_text(
                    tx, top + ROW_HEIGHT / 2, text=label,
                    fill=cell_color(key, row), font=font, anchor=anchor,
                ))
                x += width
            self._row_items.append({"bg": background, "texts": texts})

        height = len(self.rows) * ROW_HEIGHT
        self.canvas.configure(scrollregion=(0, 0, total_width, height))

    def _draw_sort_arrow(self, tx: float, anchor: str, width: float, x: float):
        body_font, bold_font = self._fonts()
        if anchor == "e":
            ax = tx + 4
        elif anchor == "center":
            ax = tx + self._measure(bold_font, column_title(self.sort_column)) / 2 + 6
        else:
            ax = tx + self._measure(bold_font, column_title(self.sort_column)) + 6
        ax = min(ax, x + width - 6)
        cy = HEADER_HEIGHT / 2
        if self.sort_descending:
            points = [ax - 4, cy - 2, ax + 4, cy - 2, ax, cy + 3]
        else:
            points = [ax - 4, cy + 2, ax + 4, cy + 2, ax, cy - 3]
        self.header.create_polygon(points, fill=t.ACCENT_TEXT, outline="")

    def _row_bg(self, index: int, row: Row) -> str:
        if row.key == self.selected_key:
            return t.BG_ROW_SELECTED
        if index == self._hover_index:
            return t.BG_ROW_HOVER
        return t.BG_ROW_ALT if index % 2 else t.BG

    def _paint_backgrounds(self):
        for index, (row, items) in enumerate(zip(self.rows, self._row_items)):
            self.canvas.itemconfigure(items["bg"], fill=self._row_bg(index, row))

    # -- interaction ---------------------------------------------------
    def _row_at(self, event) -> int | None:
        y = self.canvas.canvasy(event.y)
        index = int(y // ROW_HEIGHT)
        if 0 <= index < len(self.rows):
            return index
        return None

    def _set_hover(self, index: int | None):
        if index == self._hover_index:
            return
        self._hover_index = index
        self._paint_backgrounds()

    def _on_motion(self, event):
        self._set_hover(self._row_at(event))

    def _on_click(self, event):
        index = self._row_at(event)
        if index is None:
            return
        self.select_key(self.rows[index].key)

    def _on_double_click(self, event):
        index = self._row_at(event)
        if index is not None and self.on_activate:
            self.on_activate(self.rows[index])

    def _column_at(self, event) -> str | None:
        x = self.header.canvasx(event.x)
        edge = 0.0
        for key, width in zip(self.columns, self._widths or self._layout()):
            if edge <= x < edge + width:
                return key
            edge += width
        return None

    def _on_header_motion(self, event):
        self.header.configure(
            cursor="hand2" if self._column_at(event) else "arrow")

    def _on_header_click(self, event):
        key = self._column_at(event)
        if key is None:
            return
        if key == self.sort_column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = key
            # Numbers are most useful biggest-first; names A-Z.
            self.sort_descending = COLUMN_BY_KEY[key].numeric
        if self.on_sort:
            self.on_sort(key, self.sort_descending)


def _anchor_for(anchor: str, x: float, width: float) -> tuple[str, float]:
    if anchor == "e":
        return "e", x + width - CELL_PAD
    if anchor == "center":
        return "center", x + width / 2
    return "w", x + CELL_PAD


def cell_color(key: str, row: Row) -> str:
    """Per-cell text colour — the reason this table isn't a Treeview."""
    if key in ("overall", "profit_index"):
        value = row.get(key) or 0
        if value >= 60:
            return t.GREEN
        if value >= 30:
            return t.GREEN_DIM
        return t.FG_DIM
    if key in ("est_profit", "roi"):
        value = row.get(key)
        if value is None:
            return t.FG_DIM
        return t.GREEN if value > 0 else t.RED
    if key == "name":
        return t.FG
    if key == "url":
        return t.ACCENT_TEXT
    if COLUMN_BY_KEY[key].numeric:
        return t.FG
    return t.FG_MUTED

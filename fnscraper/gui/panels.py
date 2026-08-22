"""The Map, Calendar, Charts and Export tabs.

All four are drawn on canvases that repaint on resize, so the window has
no fixed layout and no image assets to ship.
"""

from __future__ import annotations

import calendar as calendar_module
import math
import os
import subprocess
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Sequence

from .. import config
from . import icons, theme as t
from .viewmodel import Row, compact_money, format_value
from .widgets import (CheckBox, FlatButton, IconButton, RadioGroup, RadioItem,
                      ScrollFrame, SectionTitle, TextField, Tooltip, bind_wheel)

MILES_PER_DEGREE = 69.0


def open_folder(path: Path) -> bool:
    """Reveal a directory in the platform's file manager."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))                  # noqa: S606 (Windows only)
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

class MapPanel(tk.Frame):
    """Every result plotted against home, with drive-time rings."""

    def __init__(self, parent: tk.Misc,
                 on_select: Callable[[Row], None] | None = None, **kw):
        super().__init__(parent, bg=t.BG, **kw)
        self.rows: list[Row] = []
        self.on_select = on_select
        self._points: list[tuple[float, float, Row]] = []
        self.canvas = tk.Canvas(self, bg="#17171a", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Button-1>", self._click)
        self._tip: int | None = None

    def set_rows(self, rows: Sequence[Row]):
        self.rows = [r for r in rows if r.event.lat is not None]
        self.redraw()

    # -- projection ----------------------------------------------------
    def _bounds(self):
        lats = [config.HOME_LAT] + [r.event.lat for r in self.rows]
        lons = [config.HOME_LON] + [r.event.lon for r in self.rows]
        pad = 1.2
        return (min(lats) - pad, max(lats) + pad,
                min(lons) - pad, max(lons) + pad)

    def redraw(self):
        c = self.canvas
        c.delete("all")
        self._points = []
        width, height = c.winfo_width(), c.winfo_height()
        if width < 40 or height < 40:
            return
        if not self.rows:
            c.create_text(width / 2, height / 2,
                          text="No located events yet — run a scrape, or load "
                               "a saved results file.",
                          fill=t.FG_DIM, font=t.UI_SMALL)
            return

        lat0, lat1, lon0, lon1 = self._bounds()
        mid_lat = (lat0 + lat1) / 2
        squeeze = max(0.2, math.cos(math.radians(mid_lat)))
        margin = 28
        span_x = (lon1 - lon0) * squeeze
        span_y = lat1 - lat0
        scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
        off_x = (width - span_x * scale) / 2
        off_y = (height - span_y * scale) / 2

        def project(lat: float, lon: float) -> tuple[float, float]:
            return (off_x + (lon - lon0) * squeeze * scale,
                    off_y + (lat1 - lat) * scale)

        # graticule
        for lon in range(int(lon0), int(lon1) + 1, 5):
            x, _ = project(lat0, lon)
            c.create_line(x, 0, x, height, fill="#202024")
        for lat in range(int(lat0), int(lat1) + 1, 3):
            _, y = project(lat, lon0)
            c.create_line(0, y, width, y, fill="#202024")

        # drive-time rings, in straight-line miles the model would allow
        hx, hy = project(config.HOME_LAT, config.HOME_LON)
        for hours, color in ((5, "#2b3a4a"), (10, "#2b4a3a"), (15, "#4a3a2b")):
            miles = hours * config.AVG_MPH / config.ROAD_CIRCUITY
            radius = miles / MILES_PER_DEGREE * scale
            c.create_oval(hx - radius, hy - radius, hx + radius, hy + radius,
                          outline=color, dash=(3, 4))
            c.create_text(hx, hy - radius + 10, text=f"{hours} h",
                          fill=color, font=t.UI_TINY)

        for row in sorted(self.rows, key=lambda r: r.get("overall") or 0):
            x, y = project(row.event.lat, row.event.lon)
            score = row.get("overall") or 0
            attendance = row.get("attendance") or 0
            radius = 3 + min(7.0, math.sqrt(max(attendance, 1)) / 90)
            color = t.GREEN if score >= 60 else (t.AMBER if score >= 30 else t.FG_DIM)
            c.create_oval(x - radius, y - radius, x + radius, y + radius,
                          fill=color, outline="#101013")
            self._points.append((x, y, row))

        icons.draw(c, "pin", hx - 9, hy - 20, 20, t.ACCENT_TEXT, 1.8)
        c.create_text(hx, hy + 6, text=config.HOME_NAME, fill=t.ACCENT_TEXT,
                      font=t.UI_TINY_BOLD, anchor="n")

        legend = [("Strong score", t.GREEN), ("Middling", t.AMBER),
                  ("Weak / unprofitable", t.FG_DIM)]
        for index, (label, color) in enumerate(legend):
            y = height - 18 - index * 16
            c.create_oval(16, y - 4, 24, y + 4, fill=color, outline="")
            c.create_text(32, y, text=label, fill=t.FG_MUTED, font=t.UI_TINY,
                          anchor="w")
        c.create_text(width - 14, height - 14,
                      text=f"{len(self.rows):,} located events · dot size = attendance",
                      fill=t.FG_DIM, font=t.UI_TINY, anchor="se")

    # -- interaction ---------------------------------------------------
    def _nearest(self, event) -> Row | None:
        best, best_distance = None, 12.0
        for x, y, row in self._points:
            distance = math.hypot(event.x - x, event.y - y)
            if distance < best_distance:
                best, best_distance = row, distance
        return best

    def _hover(self, event):
        row = self._nearest(event)
        if self._tip is not None:
            self.canvas.delete(self._tip)
            self._tip = None
        self.canvas.configure(cursor="hand2" if row else "arrow")
        if row is None:
            return
        text = (f"{row.event.name}\n{row.event.city}, {row.event.state} · "
                f"{row.text('dates')}\nScore {row.text('overall')} · "
                f"profit {format_value('money', row.get('est_profit'))}")
        self._tip = self.canvas.create_text(
            event.x + 12, event.y - 12, text=text, fill=t.FG,
            font=t.UI_TINY, anchor="nw", justify="left",
        )
        box = self.canvas.bbox(self._tip)
        if box:
            back = self.canvas.create_rectangle(
                box[0] - 6, box[1] - 4, box[2] + 6, box[3] + 4,
                fill=t.BG_POPUP, outline=t.BORDER)
            self.canvas.tag_lower(back, self._tip)
            self._tip = self.canvas.create_text(
                event.x + 12, event.y - 12, text=text, fill=t.FG,
                font=t.UI_TINY, anchor="nw", justify="left")

    def _click(self, event):
        row = self._nearest(event)
        if row is not None and self.on_select:
            self.on_select(row)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

class CalendarPanel(tk.Frame):
    """A month grid showing which shows run on which days."""

    def __init__(self, parent: tk.Misc,
                 on_select: Callable[[Row], None] | None = None, **kw):
        super().__init__(parent, bg=t.BG, **kw)
        self.rows: list[Row] = []
        self.on_select = on_select
        today = date.today()
        self.year, self.month = today.year, today.month
        self._chips: list[tuple[float, float, float, float, Row]] = []

        bar = tk.Frame(self, bg=t.BG)
        bar.pack(fill="x", padx=12, pady=(12, 6))
        IconButton(bar, "chevron-left", lambda: self.shift(-1)).pack(side="left")
        self.title = tk.Label(bar, text="", bg=t.BG, fg=t.FG, font=t.UI_BOLD,
                              width=18)
        self.title.pack(side="left", padx=4)
        IconButton(bar, "chevron-right", lambda: self.shift(1)).pack(side="left")
        FlatButton(bar, "Today", self.go_today, kind="ghost").pack(
            side="left", padx=(10, 0))
        self.summary = tk.Label(bar, text="", bg=t.BG, fg=t.FG_MUTED,
                                font=t.UI_SMALL)
        self.summary.pack(side="right")

        self.canvas = tk.Canvas(self, bg=t.BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Button-1>", self._click)

    def set_rows(self, rows: Sequence[Row]):
        self.rows = list(rows)
        first = min((r.get("start_date") for r in self.rows
                     if r.get("start_date")), default=None)
        if first is not None and (first.year, first.month) > (self.year, self.month):
            self.year, self.month = first.year, first.month
        self.redraw()

    def shift(self, months: int):
        month = self.month - 1 + months
        self.year += month // 12
        self.month = month % 12 + 1
        self.redraw()

    def go_today(self):
        today = date.today()
        self.year, self.month = today.year, today.month
        self.redraw()

    def _events_by_day(self) -> dict[date, list[Row]]:
        days: dict[date, list[Row]] = {}
        for row in self.rows:
            for day in row.event.open_dates():
                if (day.year, day.month) == (self.year, self.month):
                    days.setdefault(day, []).append(row)
        for group in days.values():
            group.sort(key=lambda r: -(r.get("overall") or 0))
        return days

    def redraw(self):
        c = self.canvas
        c.delete("all")
        self._chips = []
        width, height = c.winfo_width(), c.winfo_height()
        self.title.configure(
            text=f"{calendar_module.month_name[self.month]} {self.year}")
        if width < 60 or height < 60:
            return

        by_day = self._events_by_day()
        self.summary.configure(
            text=f"{sum(len(v) for v in by_day.values()):,} show-days this month"
                 f" · {len(self.rows):,} events loaded")

        head = 22
        cell_w = width / 7
        weeks = calendar_module.monthcalendar(self.year, self.month)
        cell_h = max(60.0, (height - head) / max(1, len(weeks)))
        for index, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            c.create_text(index * cell_w + cell_w / 2, head / 2, text=name,
                          fill=t.FG_DIM, font=t.UI_TINY_BOLD)

        today = date.today()
        for week_index, week in enumerate(weeks):
            for day_index, day in enumerate(week):
                x0 = day_index * cell_w
                y0 = head + week_index * cell_h
                x1, y1 = x0 + cell_w - 3, y0 + cell_h - 3
                if day == 0:
                    c.create_rectangle(x0, y0, x1, y1, fill="#1b1b1d",
                                       outline=t.BORDER_SOFT)
                    continue
                current = date(self.year, self.month, day)
                events = by_day.get(current, [])
                weekend = day_index >= 5
                fill = t.BG_CARD if events else ("#1d1d20" if weekend else t.BG)
                outline = t.ACCENT if current == today else t.BORDER_SOFT
                c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline)
                c.create_text(x0 + 7, y0 + 6, text=str(day),
                              fill=t.FG if events else t.FG_DIM,
                              font=t.UI_TINY_BOLD, anchor="nw")

                chip_y = y0 + 22
                for row in events[:3]:
                    if chip_y + 16 > y1:
                        break
                    score = row.get("overall") or 0
                    color = t.GREEN if score >= 60 else (
                        t.AMBER if score >= 30 else t.FG_DIM)
                    c.create_rectangle(x0 + 5, chip_y + 1, x0 + 8, chip_y + 13,
                                       fill=color, outline="")
                    # Anchored to the top, not the middle: a name that wraps
                    # to two lines would otherwise grow upwards into the day
                    # number above it.
                    text_id = c.create_text(
                        x0 + 12, chip_y, text=row.event.name, fill=t.FG,
                        font=t.UI_TINY, anchor="nw",
                        width=max(20, cell_w - 20))
                    box = c.bbox(text_id)
                    bottom = box[3] if box else chip_y + 14
                    self._chips.append((x0 + 5, chip_y, x1, bottom, row))
                    chip_y = bottom + 3
                if len(events) > 3:
                    c.create_text(x0 + 7, y1 - 6,
                                  text=f"+{len(events) - 3} more",
                                  fill=t.FG_DIM, font=t.UI_TINY, anchor="sw")

    def _click(self, event):
        for x0, y0, x1, y1, row in self._chips:
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if self.on_select:
                    self.on_select(row)
                return


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

class ChartsPanel(tk.Frame):
    """Four small multiples: profit, months, categories, score spread."""

    def __init__(self, parent: tk.Misc, **kw):
        super().__init__(parent, bg=t.BG, **kw)
        self.rows: list[Row] = []
        self.canvas = tk.Canvas(self, bg=t.BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())

    def set_rows(self, rows: Sequence[Row]):
        self.rows = list(rows)
        self.redraw()

    def redraw(self):
        c = self.canvas
        c.delete("all")
        width, height = c.winfo_width(), c.winfo_height()
        if width < 80 or height < 80:
            return
        if not self.rows:
            c.create_text(width / 2, height / 2, fill=t.FG_DIM, font=t.UI_SMALL,
                          text="Charts appear once there are results to chart.")
            return

        gap = 12
        half_w = (width - gap) / 2
        half_h = (height - gap) / 2
        self._profit_chart(0, 0, half_w, half_h)
        self._month_chart(half_w + gap, 0, half_w, half_h)
        self._category_chart(0, half_h + gap, half_w, half_h)
        self._score_chart(half_w + gap, half_h + gap, half_w, half_h)

    # -- helpers -------------------------------------------------------
    def _frame(self, x, y, w, h, title: str) -> float:
        self.canvas.create_rectangle(x, y, x + w, y + h, fill=t.BG_CARD,
                                     outline=t.BORDER)
        self.canvas.create_text(x + 14, y + 14, text=title, fill=t.FG,
                                font=t.UI_SMALL_BOLD, anchor="nw")
        return y + 38

    def _bars_h(self, x, y, w, h, items, color, value_text):
        """Horizontal bars: items are (label, value)."""
        if not items:
            return
        top = y
        biggest = max(abs(value) for _, value in items) or 1
        row_h = min(34.0, (h - 16) / len(items))
        label_w = min(150.0, w * 0.38)
        for index, (label, value) in enumerate(items):
            cy = top + index * row_h + row_h / 2
            self.canvas.create_text(x + 14, cy, text=label, fill=t.FG_MUTED,
                                    font=t.UI_TINY, anchor="w", width=label_w)
            bar_x = x + 14 + label_w + 8
            bar_w = max(1.0, (w - (bar_x - x) - 80) * abs(value) / biggest)
            self.canvas.create_rectangle(
                bar_x, cy - row_h * 0.28, bar_x + bar_w, cy + row_h * 0.28,
                fill=color if value >= 0 else t.RED, outline="")
            self.canvas.create_text(bar_x + bar_w + 8, cy, text=value_text(value),
                                    fill=t.FG, font=t.UI_TINY, anchor="w")

    def _bars_v(self, x, y, w, h, items, color, value_text):
        if not items:
            return
        biggest = max(value for _, value in items) or 1
        # Leave headroom for the value printed above the tallest bar, or it
        # lands on the chart's title.
        headroom = 16
        plot_h = h - 44 - headroom
        column_w = (w - 28) / len(items)
        base = y + headroom + plot_h
        for index, (label, value) in enumerate(items):
            cx = x + 14 + index * column_w + column_w / 2
            bar_h = plot_h * value / biggest
            self.canvas.create_rectangle(
                cx - column_w * 0.3, base - bar_h, cx + column_w * 0.3, base,
                fill=color, outline="")
            self.canvas.create_text(cx, base - bar_h - 8, text=value_text(value),
                                    fill=t.FG_MUTED, font=t.UI_TINY)
            self.canvas.create_text(cx, base + 12, text=label, fill=t.FG_DIM,
                                    font=t.UI_TINY, width=max(28, column_w))
        self.canvas.create_line(x + 10, base, x + w - 10, base, fill=t.BORDER)

    # -- the four charts -----------------------------------------------
    def _profit_chart(self, x, y, w, h):
        top = self._frame(x, y, w, h, "Top shows by estimated profit")
        best = sorted(self.rows, key=lambda r: -(r.get("est_profit") or 0))[:6]
        items = [(r.event.name, r.get("est_profit") or 0.0) for r in best]
        self._bars_h(x, top, w, h - (top - y), items, t.GREEN,
                     lambda v: format_value("money", v))

    def _month_chart(self, x, y, w, h):
        top = self._frame(x, y, w, h, "Shows per month")
        counts: dict[tuple[int, int], int] = {}
        for row in self.rows:
            start = row.get("start_date")
            if start:
                counts[(start.year, start.month)] = \
                    counts.get((start.year, start.month), 0) + 1
        ordered = sorted(counts.items())[:12]
        items = [(f"{calendar_module.month_abbr[m]}\n{y % 100:02d}", n)
                 for (y, m), n in ordered]
        self._bars_v(x, top, w, h - (top - y), items, t.ACCENT_TEXT,
                     lambda v: f"{int(v)}")

    def _category_chart(self, x, y, w, h):
        top = self._frame(x, y, w, h, "Shows by type")
        counts: dict[str, int] = {}
        for row in self.rows:
            label = row.get("category") or "Other"
            counts[label] = counts.get(label, 0) + 1
        items = sorted(counts.items(), key=lambda kv: -kv[1])[:8]
        self._bars_h(x, top, w, h - (top - y), items, t.PURPLE,
                     lambda v: f"{int(v)}")

    def _score_chart(self, x, y, w, h):
        top = self._frame(x, y, w, h, "Overall score spread")
        buckets = [0] * 10
        for row in self.rows:
            score = max(0.0, min(99.9, row.get("overall") or 0.0))
            buckets[int(score // 10)] += 1
        items = [(f"{i * 10}", n) for i, n in enumerate(buckets)]
        self._bars_v(x, top, w, h - (top - y), items, t.AMBER,
                     lambda v: f"{int(v)}" if v else "")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportPanel(tk.Frame):
    """Writes the current results out in the formats the CLI already knows."""

    FORMATS = (
        ("csv", "Spreadsheet-ready CSV (.csv)"),
        ("xlsx", "Excel workbook (.xlsx)"),
        ("md", "Markdown table (.md)"),
        ("json", "Reloadable results file (.json)"),
    )

    def __init__(self, parent: tk.Misc,
                 rows_provider: Callable[[str], list[Row]],
                 output_dir: str = "reports", **kw):
        super().__init__(parent, bg=t.BG, **kw)
        self.rows_provider = rows_provider
        scroller = ScrollFrame(self, bg=t.BG)
        scroller.pack(fill="both", expand=True)
        body = scroller.body

        pad = {"padx": 20}
        SectionTitle(body, "Export results", bg=t.BG).pack(
            anchor="w", pady=(18, 4), **pad)
        tk.Label(body, bg=t.BG, fg=t.FG_MUTED, font=t.UI_SMALL, justify="left",
                 anchor="w", wraplength=560,
                 text="Every export carries the full field set — each column "
                      "on the Event and every number the scoring model "
                      "derived, not just what the table shows.").pack(
            anchor="w", pady=(0, 14), **pad)

        tk.Label(body, text="Destination folder", bg=t.BG, fg=t.FG_MUTED,
                 font=t.UI_SMALL).pack(anchor="w", **pad)
        folder_row = tk.Frame(body, bg=t.BG)
        folder_row.pack(fill="x", pady=(4, 16), **pad)
        self.folder = TextField(folder_row, value=str(Path(output_dir).resolve()),
                                width=52)
        self.folder.pack(side="left", fill="x", expand=True)
        FlatButton(folder_row, "Browse…", self._browse).pack(side="left", padx=6)
        FlatButton(folder_row, "Open", self._open, icon="folder").pack(side="left")

        tk.Label(body, text="Formats", bg=t.BG, fg=t.FG_MUTED,
                 font=t.UI_SMALL).pack(anchor="w", **pad)
        self.formats: dict[str, CheckBox] = {}
        for key, label in self.FORMATS:
            box = CheckBox(body, label, value=key in ("csv", "xlsx"), bg=t.BG)
            box.pack(anchor="w", pady=2, **pad)
            self.formats[key] = box

        tk.Label(body, text="Which rows", bg=t.BG, fg=t.FG_MUTED,
                 font=t.UI_SMALL).pack(anchor="w", pady=(14, 4), **pad)
        self.scope = RadioGroup("filtered")
        for value, label in (
            ("filtered", "The rows the current search leaves on screen"),
            ("all", "Every result from the last scrape"),
            ("selected", "Only the row selected in the table"),
        ):
            RadioItem(body, self.scope, value, label, bg=t.BG).pack(
                anchor="w", pady=2, **pad)

        actions = tk.Frame(body, bg=t.BG)
        actions.pack(fill="x", pady=(18, 8), **pad)
        FlatButton(actions, "Export now", self.export, icon="export",
                   kind="primary").pack(side="left")
        self.status = tk.Label(actions, text="", bg=t.BG, fg=t.FG_MUTED,
                               font=t.UI_SMALL)
        self.status.pack(side="left", padx=12)

        self.log = tk.Text(body, height=9, bg=t.BG_CARD, fg=t.FG_MUTED,
                           font=t.MONO, relief="flat", bd=0, wrap="none",
                           highlightthickness=1, highlightbackground=t.BORDER,
                           insertbackground=t.FG)
        self.log.pack(fill="both", expand=True, pady=(6, 20), **pad)
        self.log.configure(state="disabled")
        bind_wheel(self.log, lambda step: self.log.yview_scroll(step, "units"))

    # -- helpers -------------------------------------------------------
    def set_folder(self, path: str):
        self.folder.set(str(Path(path).resolve()))

    def _browse(self):
        chosen = filedialog.askdirectory(initialdir=self.folder.get() or ".")
        if chosen:
            self.set_folder(chosen)

    def _open(self):
        open_folder(Path(self.folder.get() or "."))

    def _write(self, message: str):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # -- the actual export ---------------------------------------------
    def export(self):
        from .. import export as export_module
        from .. import persist

        rows = self.rows_provider(self.scope.value)
        if not rows:
            self.status.configure(text="Nothing to export.", fg=t.AMBER)
            return
        chosen = [key for key, box in self.formats.items() if box.get()]
        if not chosen:
            self.status.configure(text="Pick at least one format.", fg=t.AMBER)
            return

        out_dir = Path(self.folder.get() or "reports")
        stem = f"festivals-{date.today():%Y-%m-%d}"
        scored = [row.scored for row in rows]
        written: list[Path] = []
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            if "csv" in chosen:
                written.append(export_module.export_csv(
                    scored, out_dir / f"{stem}.csv"))
            if "md" in chosen:
                written.append(export_module.export_markdown(
                    scored, out_dir / f"{stem}.md"))
            if "xlsx" in chosen:
                path = export_module.export_xlsx(scored, out_dir / f"{stem}.xlsx")
                if path is None:
                    self._write("! openpyxl is not installed — skipped .xlsx")
                else:
                    written.append(path)
            if "json" in chosen:
                written.append(persist.save_results(
                    scored, out_dir / f"{stem}.json"))
        except OSError as exc:
            self.status.configure(text=f"Export failed: {exc}", fg=t.RED)
            self._write(f"! {exc}")
            return

        self.status.configure(
            text=f"Wrote {len(written)} file(s) for {len(rows):,} shows.",
            fg=t.GREEN)
        for path in written:
            self._write(str(path))
        return written

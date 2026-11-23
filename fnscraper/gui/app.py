"""The FestivalNet Scraper window.

Layout, top to bottom: an app bar, then a settings rail beside the results
area, then a status bar.  The results area is a tab deck (Overview, Table,
Map, Calendar, Charts, Export) sitting above a detail pane for whichever
show is selected.
"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from .. import __version__, categories, config
from ..models import ScoredEvent
from . import icons, paths, places, scrape, theme as t, viewmodel as vm
from .detail import DetailPane
from .grid import DataGrid
from .panels import CalendarPanel, ChartsPanel, ExportPanel, MapPanel, open_folder
from .widgets import (CheckBox, CheckListButton, FieldLabel, FlatButton,
                      Pager, RadioGroup, RadioItem, ScrollFrame, SectionTitle,
                      Select, StatCard, TabBar, Deck, TextField, NumberField,
                      Tooltip)

RESULT_TABS = (
    ("overview", "Overview"),
    ("table", "Table"),
    ("map", "Map"),
    ("calendar", "Calendar"),
    ("charts", "Charts"),
    ("export", "Export"),
)
SIDEBAR_WIDTH = 312
DETAIL_HEIGHT = 300
DATE_FORMAT = "%m/%d/%Y"
# Typing waits this long for the next key before re-filtering, so a word
# costs one refresh rather than one per letter.
TYPING_DEBOUNCE_MS = 180
# How often the window checks on a scrape or a file load, and how often
# it looks when neither is happening.
PUMP_BUSY_MS = 150
PUMP_IDLE_MS = 600
# Result views that are redrawn only while their tab is showing.
LAZY_VIEWS = ("overview", "table", "map", "calendar", "charts")


class ScraperWindow(tk.Tk):
    def __init__(self, *, sample: bool = False, results_file: Path | None = None):
        super().__init__()
        self.title(paths.APP_NAME)
        self.geometry("1500x940")
        self.minsize(1120, 700)
        self.configure(bg=t.BG)
        t.init(self)
        self._set_window_icon()

        self.all_rows: list[vm.Row] = []
        self.rows: list[vm.Row] = []
        self.page = 1
        self.page_size = vm.DEFAULT_PAGE_SIZE
        self.sort_order = vm.DEFAULT_SORT
        self.column_sort: tuple[str, bool] | None = None
        self.search_text = ""
        self.sample_data = False
        self.results_path: Path | None = None
        self.last_progress = scrape.Progress()
        self.controller = scrape.ScrapeController(self._on_scrape_event)
        # Saved results are read off the Tk thread: the file can sit in an
        # iCloud-synced Documents folder, where a read blocks until macOS
        # downloads it, and the window has to stay alive meanwhile.
        self._loads: queue.Queue = queue.Queue()
        self._load_token = 0
        self._loads_in_flight = 0
        self._refresh_job: str | None = None
        self._pump_job: str | None = None
        self._stale: set[str] = set(LAZY_VIEWS)

        self.output_dir = paths.default_output_dir()
        self.cache_root = paths.cache_dir()

        self._build_menu()
        self._build_app_bar()
        body = tk.Frame(self, bg=t.BG)
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._build_content(body)
        self._build_status_bar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _e: self._stop_scrape())
        self.bind("<Control-r>", lambda _e: self._start_scrape())
        self.bind("<Control-e>", lambda _e: self._export_all())

        self._restore_settings()
        self._pump_job = self.after(120, self._pump)
        if results_file is not None:
            self.load_results_in_background(results_file)
        elif sample:
            self.load_sample()
        else:
            self._autoload_last_results()

    # ------------------------------------------------------------------
    # chrome
    # ------------------------------------------------------------------
    def _set_window_icon(self):
        icon = paths.resource_dir() / "assets" / "icons" / "festivalnet-256.png"
        if icon.is_file():
            try:
                self._icon_image = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon_image)
            except tk.TclError:               # pragma: no cover - Tk build
                pass

    MENU_COLORS = dict(
        bg=t.BG_BAR, fg=t.FG, activebackground=t.ACCENT,
        activeforeground="#ffffff", relief="flat", borderwidth=0,
    )

    def _build_menu(self):
        menubar = tk.Menu(self, **self.MENU_COLORS)
        file_menu = tk.Menu(menubar, tearoff=0, **self.MENU_COLORS)
        file_menu.add_command(label="Open results…", command=self._open_results)
        file_menu.add_command(label="Save results as…", command=self._save_results_as)
        file_menu.add_separator()
        file_menu.add_command(label="Export all…", command=self._export_all)
        file_menu.add_command(label="Open data folder",
                              command=lambda: open_folder(self.output_dir))
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        run_menu = tk.Menu(menubar, tearoff=0, **self.MENU_COLORS)
        run_menu.add_command(label="Start scraping", command=self._start_scrape)
        run_menu.add_command(label="Stop", command=self._stop_scrape)
        run_menu.add_separator()
        run_menu.add_command(label="Load sample data", command=self.load_sample)
        run_menu.add_command(label="Clear results", command=self.clear_results)
        menubar.add_cascade(label="Scrape", menu=run_menu)

        help_menu = tk.Menu(menubar, tearoff=0, **self.MENU_COLORS)
        help_menu.add_command(label="About", command=self._about)
        help_menu.add_command(
            label="Project page",
            command=lambda: webbrowser.open(
                "https://github.com/jordolang/festivalnetwork-scraper"))
        menubar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menubar)

    def _build_app_bar(self):
        bar = tk.Frame(self, bg=t.BG_BAR, height=38)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        mark = tk.Canvas(bar, width=18, height=18, bg=t.BG_BAR,
                         highlightthickness=0, bd=0, takefocus=0)
        mark.pack(side="left", padx=(12, 8))
        icons.draw(mark, "logo", 0, 0, 18, t.ACCENT_TEXT, 1.4)
        tk.Label(bar, text=paths.APP_NAME, bg=t.BG_BAR, fg=t.FG,
                 font=t.UI_SMALL_BOLD).pack(side="left")
        self.sample_badge = tk.Label(bar, text="", bg=t.BG_BAR, fg=t.AMBER,
                                     font=t.UI_TINY_BOLD)
        self.sample_badge.pack(side="left", padx=10)
        tk.Frame(self, bg=t.BORDER, height=1).pack(fill="x")

    # ------------------------------------------------------------------
    # sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self, parent: tk.Misc):
        rail = tk.Frame(parent, bg=t.BG_SIDEBAR, width=SIDEBAR_WIDTH)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)

        footer = tk.Frame(rail, bg=t.BG_SIDEBAR)
        footer.pack(side="bottom", fill="x", padx=14, pady=12)
        FlatButton(footer, "Save Settings", self._save_settings_as,
                   icon="save", padx=8).pack(side="left", expand=True,
                                             fill="x", padx=(0, 4))
        FlatButton(footer, "Load Settings", self._load_settings_from,
                   icon="load", padx=8).pack(side="left", expand=True,
                                             fill="x", padx=(4, 0))
        tk.Frame(rail, bg=t.BORDER_SOFT, height=1).pack(side="bottom", fill="x")

        scroller = ScrollFrame(rail, bg=t.BG_SIDEBAR)
        scroller.pack(fill="both", expand=True)
        body = scroller.body
        self._sidebar_scroller = scroller
        pad = 14

        SectionTitle(body, "Settings", caps=True).pack(
            anchor="w", padx=pad, pady=(14, 8))
        SectionTitle(body, "Search").pack(anchor="w", padx=pad, pady=(0, 8))

        self.keyword = self._labelled_field(
            body, "Keyword / Event Name",
            TextField(body, placeholder="e.g. craft, harvest, salsa",
                      on_change=lambda _v: self._refresh_soon()))
        self.location = self._labelled_field(
            body, "Location",
            TextField(body, placeholder="City, State or ZIP",
                      on_change=lambda _v: self._refresh_soon()))

        self.country = self._labelled_field(
            body, "Country",
            Select(body, places.COUNTRIES, places.ALL_COUNTRIES,
                   self._on_country_change, width=SIDEBAR_WIDTH - 2 * pad))
        self.state = self._labelled_field(
            body, "State / Province",
            Select(body, self._state_options(places.ALL_COUNTRIES),
                   vm.ALL_STATES, lambda _v: self._refresh(reset_page=True),
                   width=SIDEBAR_WIDTH - 2 * pad))
        self.event_type = self._labelled_field(
            body, "Event Type",
            Select(body, self._type_options(), vm.ALL_TYPES,
                   lambda _v: self._refresh(reset_page=True),
                   width=SIDEBAR_WIDTH - 2 * pad))

        start, end = scrape.default_date_range()
        FieldLabel(body, "Date Range").pack(anchor="w", padx=pad, pady=(10, 3))
        dates = tk.Frame(body, bg=t.BG_SIDEBAR)
        dates.pack(fill="x", padx=pad)
        self.date_from = TextField(
            dates, value=start.strftime(DATE_FORMAT), width=9,
            on_change=lambda _v: self._refresh_soon())
        self.date_from.pack(side="left", fill="x", expand=True)
        tk.Label(dates, text="to", bg=t.BG_SIDEBAR, fg=t.FG_MUTED,
                 font=t.UI_SMALL).pack(side="left", padx=5)
        self.date_to = TextField(
            dates, value=end.strftime(DATE_FORMAT), width=9,
            on_change=lambda _v: self._refresh_soon())
        self.date_to.pack(side="left", fill="x", expand=True)

        FieldLabel(body, "Min / Max Attendance").pack(
            anchor="w", padx=pad, pady=(10, 3))
        attendance = tk.Frame(body, bg=t.BG_SIDEBAR)
        attendance.pack(fill="x", padx=pad)
        self.min_attendance = TextField(
            attendance, placeholder="Min", width=8,
            on_change=lambda _v: self._refresh_soon())
        self.min_attendance.pack(side="left", fill="x", expand=True)
        tk.Label(attendance, text="–", bg=t.BG_SIDEBAR, fg=t.FG_MUTED,
                 font=t.UI_SMALL).pack(side="left", padx=5)
        self.max_attendance = TextField(
            attendance, placeholder="Max", width=8,
            on_change=lambda _v: self._refresh_soon())
        self.max_attendance.pack(side="left", fill="x", expand=True)

        toggles = tk.Frame(body, bg=t.BG_SIDEBAR)
        toggles.pack(fill="x", padx=pad, pady=(12, 4))
        # Not uniform: equal halves clip "Search by Location", which is
        # wider than "Search by Date" by exactly the amount that matters.
        toggles.columnconfigure(0, weight=0, minsize=116)
        toggles.columnconfigure(1, weight=1)
        self.use_dates = self._grid_check(toggles, "Search by Date", 0, 0, True)
        self.use_location = self._grid_check(toggles, "Search by Location", 0, 1, True)
        self.exact_match = self._grid_check(toggles, "Exact Match", 1, 0, False)
        self.include_past = self._grid_check(
            toggles, "Include Past Festivals", 1, 1, True)

        tk.Frame(body, bg=t.BORDER_SOFT, height=1).pack(
            fill="x", padx=pad, pady=(14, 0))
        SectionTitle(body, "Scraping options", caps=True).pack(
            anchor="w", padx=pad, pady=(12, 8))

        self.all_pages = self._check(body, "Scrape All Pages", True)
        self.delay = self._number_row(
            body, "Delay Between Requests (seconds)",
            config.REQUEST_DELAY_SECONDS, 0.0, 30.0, 0.5, decimals=1)
        self.jobs = self._number_row(
            body, "Max Concurrent Requests", config.DEFAULT_JOBS, 1, 16, 1)
        self.retry_failed = self._check(body, "Retry Failed Requests", True)
        self.scrape_details = self._check(body, "Scrape Festival Details", True)
        self.geocode = self._check(body, "Geocode & Distance Filter", True)
        self.drive_hours = self._number_row(
            body, "Max Drive Hours (one way)", config.MAX_DRIVE_HOURS,
            1, 48, 1, decimals=0)
        self.include_contact = self._check(body, "Scrape Contact Information", True)
        self.include_fees = self._check(body, "Scrape Fee & Financial Info", True)
        self.refresh_cache = self._check(body, "Ignore Cached Pages", False)

        tk.Frame(body, bg=t.BORDER_SOFT, height=1).pack(
            fill="x", padx=pad, pady=(14, 0))
        SectionTitle(body, "Organize & rank results by", caps=True).pack(
            anchor="w", padx=pad, pady=(12, 8))
        self.rank = RadioGroup(vm.DEFAULT_SORT, self._on_rank_change)
        for key, label in vm.SORT_ORDERS:
            RadioItem(body, self.rank, key, label).pack(
                anchor="w", padx=pad, pady=2)
        tk.Frame(body, bg=t.BG_SIDEBAR, height=10).pack()

    def _labelled_field(self, parent: tk.Misc, label: str, widget: tk.Widget):
        FieldLabel(parent, label).pack(anchor="w", padx=14, pady=(10, 3))
        widget.pack(fill="x", padx=14)
        return widget

    def _check(self, parent: tk.Misc, label: str, value: bool) -> CheckBox:
        box = CheckBox(parent, label, value)
        box.pack(anchor="w", padx=14, pady=3)
        return box

    def _grid_check(self, parent: tk.Misc, label: str, row: int, column: int,
                    value: bool) -> CheckBox:
        box = CheckBox(parent, label, value,
                       command=lambda _v: self._refresh(reset_page=True))
        box.grid(row=row, column=column, sticky="w", pady=3)
        return box

    def _number_row(self, parent: tk.Misc, label: str, value: float,
                    minimum: float, maximum: float, step: float,
                    decimals: int = 0) -> NumberField:
        row = tk.Frame(parent, bg=t.BG_SIDEBAR)
        row.pack(fill="x", padx=14, pady=3)
        FieldLabel(row, label, wraplength=170, justify="left").pack(
            side="left", fill="x", expand=True)
        field = NumberField(row, value=value, minimum=minimum, maximum=maximum,
                            step=step, decimals=decimals, width=4)
        field.pack(side="right")
        return field

    def _state_options(self, country: str):
        options = [(vm.ALL_STATES, vm.ALL_STATES)]
        options += [(places.label(p), places.label(p))
                    for p in places.places_for(country)]
        return options

    def _type_options(self):
        options = [(vm.ALL_TYPES, vm.ALL_TYPES)]
        options += [(c.key, c.label) for c in categories.CATEGORIES]
        return options

    def _on_country_change(self, country: str):
        self.state.set_options(self._state_options(country), vm.ALL_STATES,
                               notify=False)
        self.state.set(vm.ALL_STATES)
        self._refresh(reset_page=True)

    def _on_rank_change(self, order: str):
        self.sort_order = order
        self.column_sort = None
        self.sorted_by.set(order)
        self._refresh(reset_page=True)

    # ------------------------------------------------------------------
    # content
    # ------------------------------------------------------------------
    def _build_content(self, parent: tk.Misc):
        content = tk.Frame(parent, bg=t.BG)
        content.pack(side="left", fill="both", expand=True)
        tk.Frame(content, bg=t.BORDER, width=1).place(
            x=0, y=0, relheight=1, width=1)

        header = tk.Frame(content, bg=t.BG)
        header.pack(fill="x", padx=18, pady=(14, 0))
        self.results_title = tk.Label(header, text="Results (0 festivals)",
                                      bg=t.BG, fg=t.FG, font=t.UI_TITLE)
        self.results_title.pack(side="left")

        buttons = tk.Frame(header, bg=t.BG)
        buttons.pack(side="right")
        self.open_folder_button = FlatButton(
            buttons, "Open Folder", lambda: open_folder(self.output_dir),
            icon="folder")
        self.open_folder_button.pack(side="right", padx=(8, 0))
        self.export_button = FlatButton(buttons, "Export All", self._export_all,
                                        icon="export")
        self.export_button.pack(side="right", padx=(8, 0))
        self.stop_button = FlatButton(buttons, "Stop", self._stop_scrape,
                                      icon="stop", icon_color=t.RED)
        self.stop_button.pack(side="right", padx=(8, 0))
        self.stop_button.set_enabled(False)
        self.start_button = FlatButton(buttons, "Start Scraping",
                                       self._start_scrape, icon="play",
                                       kind="primary")
        self.start_button.pack(side="right")

        self.tabs = TabBar(content, RESULT_TABS, self._on_tab_change, bg=t.BG)
        self.tabs.pack(fill="x", padx=10, pady=(10, 0))
        tk.Frame(content, bg=t.BORDER_SOFT, height=1).pack(fill="x")
        self.progress_bar = tk.Canvas(content, height=2, bg=t.BG,
                                      highlightthickness=0, bd=0)
        self.progress_bar.pack(fill="x")

        # detail pane first: packed to the bottom so the deck keeps the rest
        self.detail_holder = tk.Frame(content, bg=t.BG, height=DETAIL_HEIGHT)
        self.detail_holder.pack(side="bottom", fill="x", padx=14, pady=(0, 8))
        self.detail_holder.pack_propagate(False)
        self.detail = DetailPane(self.detail_holder)
        self.detail.pack(fill="both", expand=True)
        self._build_sash(content)

        self.deck = Deck(content, bg=t.BG)
        self.deck.pack(fill="both", expand=True)
        self._build_overview(self.deck.page("overview"))
        self._build_table(self.deck.page("table"))
        self.map_panel = MapPanel(self.deck.page("map"), self._select_row)
        self.map_panel.pack(fill="both", expand=True)
        self.calendar_panel = CalendarPanel(self.deck.page("calendar"),
                                            self._select_row)
        self.calendar_panel.pack(fill="both", expand=True)
        self.charts_panel = ChartsPanel(self.deck.page("charts"))
        self.charts_panel.pack(fill="both", expand=True)
        self.export_panel = ExportPanel(self.deck.page("export"),
                                        self._rows_for_export,
                                        str(self.output_dir))
        self.export_panel.pack(fill="both", expand=True)
        self.deck.show("overview")

    def _build_sash(self, parent: tk.Misc):
        """A drag handle for resizing the detail pane."""
        sash = tk.Frame(parent, bg=t.BG, height=6, cursor="sb_v_double_arrow")
        sash.pack(side="bottom", fill="x")
        grip = tk.Frame(sash, bg=t.BORDER, height=2, width=60)
        grip.place(relx=0.5, rely=0.5, anchor="center")
        state = {"y": 0, "height": DETAIL_HEIGHT}

        def press(event):
            state["y"] = event.y_root
            state["height"] = self.detail_holder.winfo_height()

        def drag(event):
            delta = state["y"] - event.y_root
            height = max(0, min(620, state["height"] + delta))
            self.detail_holder.configure(height=height)

        sash.bind("<Button-1>", press)
        sash.bind("<B1-Motion>", drag)
        grip.bind("<Button-1>", press)
        grip.bind("<B1-Motion>", drag)

    def _build_overview(self, parent: tk.Frame):
        cards = tk.Frame(parent, bg=t.BG)
        cards.pack(fill="x", padx=14, pady=(14, 10))
        self.cards: list[StatCard] = []
        for index, (value, label, glyph) in enumerate(
                vm.cards_for(vm.Summary())):
            card = StatCard(cards, value, label, glyph,
                            t.CARD_ACCENTS[index % len(t.CARD_ACCENTS)])
            card.grid(row=0, column=index, sticky="nsew",
                      padx=(0 if index == 0 else 8, 0))
            cards.columnconfigure(index, weight=1, uniform="cards")
            self.cards.append(card)

        controls = tk.Frame(parent, bg=t.BG)
        controls.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(controls, text="Sorted By:", bg=t.BG, fg=t.FG_MUTED,
                 font=t.UI_SMALL).pack(side="left", padx=(0, 8))
        self.sorted_by = Select(
            controls, list(vm.SORT_ORDERS), vm.DEFAULT_SORT,
            self._on_sorted_by, width=250)
        self.sorted_by.pack(side="left")

        self.columns_button = CheckListButton(
            controls, "Columns", [(c.key, vm.column_title(c.key))
                                  for c in vm.COLUMNS],
            vm.DEFAULT_COLUMNS, self._on_columns_change)
        self.columns_button.pack(side="right")
        self.search = TextField(controls, placeholder="Search results…",
                                icon="search", width=26,
                                on_change=self._on_search_typed)
        self.search.pack(side="right", padx=8)

        table_frame = tk.Frame(parent, bg=t.BG, highlightthickness=1,
                               highlightbackground=t.BORDER)
        table_frame.pack(fill="both", expand=True, padx=14)
        self.grid_view = DataGrid(
            table_frame, vm.DEFAULT_COLUMNS, on_select=self._on_grid_select,
            on_activate=self._open_listing, on_sort=self._on_column_sort,
            empty_text="No results yet — press Start Scraping, or load a "
                       "saved results file from the File menu.")
        self.grid_view.pack(fill="both", expand=True)

        footer = tk.Frame(parent, bg=t.BG)
        footer.pack(fill="x", padx=14, pady=8)
        self.pager = Pager(footer, self._go_to_page)
        self.pager.pack(side="left")
        self.page_label = tk.Label(footer, text="", bg=t.BG, fg=t.FG_MUTED,
                                   font=t.UI_SMALL)
        self.page_label.pack(side="right")
        self.page_size_select = Select(
            footer, [(str(n), f"{n} per page") for n in vm.PAGE_SIZES],
            str(vm.DEFAULT_PAGE_SIZE), self._on_page_size, width=130)
        self.page_size_select.pack(side="right", padx=10)

    def _build_table(self, parent: tk.Frame):
        head = tk.Frame(parent, bg=t.BG)
        head.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(head, text="Every column the scraper fills in", bg=t.BG,
                 fg=t.FG_MUTED, font=t.UI_SMALL).pack(side="left")
        self.table_page_label = tk.Label(head, text="", bg=t.BG, fg=t.FG_MUTED,
                                         font=t.UI_SMALL)
        self.table_page_label.pack(side="right")

        frame = tk.Frame(parent, bg=t.BG, highlightthickness=1,
                         highlightbackground=t.BORDER)
        frame.pack(fill="both", expand=True, padx=14)
        self.table_view = DataGrid(
            frame, [c.key for c in vm.COLUMNS], on_select=self._on_grid_select,
            on_activate=self._open_listing, on_sort=self._on_column_sort,
            empty_text="Nothing loaded yet.")
        self.table_view.pack(fill="both", expand=True)

        footer = tk.Frame(parent, bg=t.BG)
        footer.pack(fill="x", padx=14, pady=8)
        self.table_pager = Pager(footer, self._go_to_page)
        self.table_pager.pack(side="left")

    # ------------------------------------------------------------------
    # status bar
    # ------------------------------------------------------------------
    def _build_status_bar(self):
        tk.Frame(self, bg=t.BORDER, height=1).pack(fill="x")
        bar = tk.Frame(self, bg=t.BG_BAR, height=28)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.status = tk.Label(bar, text="Ready to scrape.", bg=t.BG_BAR,
                               fg=t.FG_MUTED, font=t.UI_SMALL, anchor="w")
        self.status.pack(side="left", padx=12)

        self.path_label = tk.Label(bar, text="", bg=t.BG_BAR, fg=t.ACCENT_TEXT,
                                   font=t.UI_SMALL, cursor="hand2")
        self.path_label.pack(side="right", padx=12)
        self.path_label.bind("<Button-1>",
                             lambda _e: open_folder(self.output_dir))
        Tooltip(self.path_label, "Open this folder")

        stats = tk.Frame(bar, bg=t.BG_BAR)
        stats.pack(side="right", padx=12)
        self.time_label = tk.Label(stats, text="Total Time: 00:00:00",
                                   bg=t.BG_BAR, fg=t.FG_MUTED, font=t.UI_SMALL)
        self.time_label.pack(side="left", padx=(0, 16))
        self.request_label = tk.Label(stats, text="Requests: 0", bg=t.BG_BAR,
                                      fg=t.FG_MUTED, font=t.UI_SMALL)
        self.request_label.pack(side="left", padx=(0, 16))
        self.failed_label = tk.Label(stats, text="Failed: 0", bg=t.BG_BAR,
                                     fg=t.FG_DIM, font=t.UI_SMALL)
        self.failed_label.pack(side="left")
        self._set_output_dir(self.output_dir)

    def _set_output_dir(self, path: Path):
        self.output_dir = Path(path)
        self.path_label.configure(
            text=f"Data saved to: {_elide_path(self.output_dir)}")
        if hasattr(self, "export_panel"):
            self.export_panel.set_folder(str(self.output_dir))

    def set_status(self, message: str, color: str = t.FG_MUTED):
        self.status.configure(text=message, fg=color)

    # ------------------------------------------------------------------
    # data plumbing
    # ------------------------------------------------------------------
    def filters(self) -> vm.Filters:
        return vm.Filters(
            keyword=self.keyword.get(),
            location=self.location.get(),
            country=self.country.get(),
            state=self.state.get(),
            event_type=self.event_type.get(),
            date_from=_parse_date(self.date_from.get()),
            date_to=_parse_date(self.date_to.get()),
            min_attendance=_parse_int(self.min_attendance.get()),
            max_attendance=_parse_int(self.max_attendance.get()),
            use_dates=self.use_dates.get(),
            use_location=self.use_location.get(),
            exact_match=self.exact_match.get(),
            include_past=self.include_past.get(),
        )

    def set_results(self, scored: list[ScoredEvent], *, sample: bool = False,
                    source: Path | None = None):
        self.all_rows = vm.build_rows(scored)
        self.sample_data = sample
        self.results_path = source
        self.sample_badge.configure(
            text="SAMPLE DATA — not a live scrape" if sample else "")
        self.page = 1
        self._refresh(reset_page=True)
        self.detail.set_row(self.rows[0] if self.rows else None)
        if self.rows:
            self.grid_view.select_key(self.rows[0].key, notify=False)

    def clear_results(self):
        self._supersede_pending_load()
        self.all_rows = []
        self.sample_data = False
        self.sample_badge.configure(text="")
        self.detail.set_row(None)
        self._refresh(reset_page=True)
        self.set_status("Cleared.")

    def _refresh_soon(self):
        """Re-filter once typing pauses, instead of on every keystroke."""
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(TYPING_DEBOUNCE_MS, self._refresh_typed)

    def _refresh_typed(self):
        self._refresh_job = None
        self._refresh(reset_page=True)

    def _refresh(self, reset_page: bool = False):
        if not hasattr(self, "grid_view"):
            return
        if self._refresh_job is not None:     # this refresh supersedes it
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        rows = self.filters().apply(self.all_rows)
        if self.search_text:
            needle = self.search_text.lower()
            rows = [r for r in rows if needle in r.search_blob()]
        if self.column_sort:
            column, descending = self.column_sort
            rows = vm.sort_by_column(rows, column, descending)
        else:
            rows = vm.sort_rows(rows, self.sort_order)
        self.rows = rows
        if reset_page:
            self.page = 1
        pages = vm.page_count(len(rows), self.page_size)
        self.page = vm.clamp_page(self.page, pages)

        summary = vm.summarize(rows)
        self.results_title.configure(
            text=f"Results ({summary.count:,} festivals)")
        for card, (value, label, _icon) in zip(self.cards,
                                                vm.cards_for(summary)):
            card.update_value(value, label)

        # Only the tab on screen is redrawn now; the rest catch up when
        # they are next shown.  Drawing all five on every keystroke —
        # 1,600 map dots, a calendar, the charts and two tables — was
        # where the time went.
        self._stale = set(LAZY_VIEWS)
        self._render_view(self.tabs.active)

    def _render_view(self, key: str):
        if key not in self._stale:
            return
        self._stale.discard(key)
        rows = self.rows
        pages = vm.page_count(len(rows), self.page_size)
        if key == "overview":
            self.grid_view.set_rows(vm.page_slice(rows, self.page, self.page_size))
            self.pager.render(self.page, pages)
            self.page_label.configure(
                text=vm.page_range_text(len(rows), self.page, self.page_size))
        elif key == "table":
            self.table_view.set_rows(vm.page_slice(rows, self.page, self.page_size))
            self.table_pager.render(self.page, pages)
            self.table_page_label.configure(
                text=vm.page_range_text(len(rows), self.page, self.page_size))
        elif key == "map":
            self.map_panel.set_rows(rows)
        elif key == "calendar":
            self.calendar_panel.set_rows(rows)
        elif key == "charts":
            self.charts_panel.set_rows(rows)

    # -- control callbacks ---------------------------------------------
    def _on_search(self, text: str):
        self.search_text = text
        self._refresh(reset_page=True)

    def _on_search_typed(self, text: str):
        self.search_text = text
        self._refresh_soon()

    def _on_sorted_by(self, order: str):
        self.sort_order = order
        self.column_sort = None
        self.rank.select(order, notify=False)
        self._refresh(reset_page=True)

    def _on_columns_change(self, keys: list[str]):
        self.grid_view.set_columns(keys)

    def _on_column_sort(self, column: str, descending: bool):
        self.column_sort = (column, descending)
        self._refresh(reset_page=True)

    def _on_page_size(self, value: str):
        self.page_size = int(value)
        self._refresh(reset_page=True)

    def _go_to_page(self, page: int):
        self.page = vm.clamp_page(page, vm.page_count(len(self.rows),
                                                      self.page_size))
        self._repage()

    def _repage(self):
        """Show another page of the same results: only the tables change."""
        self._stale |= {"overview", "table"}
        self._render_view(self.tabs.active)

    def _on_grid_select(self, row: vm.Row | None):
        self.detail.set_row(row)
        if row is not None:
            self.grid_view.selected_key = row.key
            self.table_view.selected_key = row.key
            self.grid_view._paint_backgrounds()
            self.table_view._paint_backgrounds()

    def _select_row(self, row: vm.Row):
        """Selection coming from the map or the calendar."""
        index = next((i for i, r in enumerate(self.rows) if r.key == row.key), None)
        if index is not None:
            page = index // self.page_size + 1
            if page != self.page:
                self.page = page
                self._repage()
        self.grid_view.select_key(row.key, notify=False)
        self.table_view.select_key(row.key, notify=False)
        self.detail.set_row(row)

    def _on_tab_change(self, key: str):
        self._render_view(key)          # before it is shown: no stale flash
        self.deck.show(key)
        # Map, charts and export want the whole window; the tables want
        # their detail pane.
        if key in ("overview", "table"):
            self.detail_holder.pack(side="bottom", fill="x", padx=14, pady=(0, 8))
        else:
            self.detail_holder.pack_forget()

    def _open_listing(self, row: vm.Row):
        if row.event.url:
            webbrowser.open(row.event.url)

    def _rows_for_export(self, scope: str) -> list[vm.Row]:
        if scope == "all":
            return list(self.all_rows)
        if scope == "selected":
            row = (self.grid_view.selected_row() or self.table_view.selected_row()
                   or self.detail.row)
            return [row] if row else []
        return list(self.rows)

    # ------------------------------------------------------------------
    # scraping
    # ------------------------------------------------------------------
    def crawl_options(self) -> scrape.CrawlOptions:
        return scrape.CrawlOptions(
            country=self.country.get(),
            state="" if self.state.get() == vm.ALL_STATES else self.state.get(),
            event_type="" if self.event_type.get() == vm.ALL_TYPES
            else self.event_type.get(),
            date_from=_parse_date(self.date_from.get()),
            date_to=_parse_date(self.date_to.get()),
            use_dates=self.use_dates.get(),
            max_drive_hours=self.drive_hours.value(),
            all_pages=self.all_pages.get(),
            delay=self.delay.value(),
            jobs=int(self.jobs.value()),
            retry_failed=self.retry_failed.get(),
            scrape_details=self.scrape_details.get(),
            geocode=self.geocode.get(),
            include_contact=self.include_contact.get(),
            include_fees=self.include_fees.get(),
            refresh_cache=self.refresh_cache.get(),
            output_dir=str(self.output_dir),
            cache_dir=str(self.cache_root / "pages"),
            geocode_cache=str(self.cache_root / "geocode.json"),
        )

    def _start_scrape(self):
        if self.controller.running:
            return
        try:
            settings = scrape.settings_for(self.crawl_options())
        except Exception as exc:                       # bad number in a box
            messagebox.showerror(paths.APP_NAME, f"Check the settings: {exc}")
            return
        paths.ensure(self.output_dir)
        paths.ensure(self.cache_root)
        results_path = scrape.default_results_path(self.output_dir)
        if not self.controller.start(settings, results_path):
            return
        self._supersede_pending_load()
        self.start_button.set_enabled(False)
        self.stop_button.set_enabled(True)
        self.sample_badge.configure(text="")
        self.set_status(f"Crawling {len(settings.states)} state listing(s)…",
                        t.FG)
        self._show_counters({})
        self.time_label.configure(text="Total Time: 00:00:00")
        self._draw_progress(0.0)
        self._pump_now()

    def _stop_scrape(self):
        if not self.controller.running:
            return
        self.controller.stop()
        self.stop_button.set_enabled(False)
        self.set_status("Stopping after the current request…", t.AMBER)

    def _pump(self):
        self.controller.drain()
        self._drain_loads()
        if self.controller.running:
            self.time_label.configure(
                text=f"Total Time: {scrape.format_elapsed(self.controller.elapsed)}")
            # Read the counters straight off the Fetcher rather than
            # waiting for the next progress event: the geocoding stage can
            # go a minute between ticks, and a status bar frozen at the
            # last count reads as a hung crawl.
            self._show_counters(self.controller.stats())
        busy = self.controller.running or self._loads_in_flight
        self._pump_job = self.after(PUMP_BUSY_MS if busy else PUMP_IDLE_MS,
                                    self._pump)

    def _pump_now(self):
        """Check the queues straight away rather than at the idle pace."""
        if self._pump_job is not None:
            self.after_cancel(self._pump_job)
        self._pump_job = self.after(PUMP_BUSY_MS, self._pump)

    def _on_scrape_event(self, kind: str, payload: Any):
        if kind == scrape.PROGRESS:
            self.last_progress = payload
            self._draw_progress(payload.fraction)
            label = _STAGE_LABELS.get(payload.stage, payload.stage.title())
            counter = (f" {payload.done:,}/{payload.total:,}"
                       if payload.total else "")
            self.set_status(f"{label}{counter} — {payload.message}", t.FG)
            self._show_counters({"requests": payload.requests,
                                 "failures": payload.failures})
        elif kind == scrape.FINISHED:
            self._finish_scrape(payload)
        elif kind == scrape.CANCELLED:
            self._reset_buttons()
            self._draw_progress(0.0)
            self.set_status("Stopped. Nothing was overwritten.", t.AMBER)
        elif kind == scrape.FAILED:
            self._reset_buttons()
            self._draw_progress(0.0)
            self.set_status(f"Scrape failed — {payload}", t.RED)
            messagebox.showerror(paths.APP_NAME, f"The scrape failed:\n\n{payload}")

    def _finish_scrape(self, payload: dict):
        scored = payload["scored"]
        self._reset_buttons()
        self._draw_progress(1.0)
        self.set_results(scored, sample=False, source=payload.get("path"))
        self._show_counters(payload.get("stats", {}))
        elapsed = scrape.format_elapsed(payload.get("elapsed", 0.0))
        if scored:
            self.set_status(
                f"Done in {elapsed} — {len(scored):,} scored events.", t.GREEN)
        else:
            self.set_status(
                "Done, but nothing matched. Widen the date range, the event "
                "type, or the drive limit.", t.AMBER)
        self.time_label.configure(text=f"Total Time: {elapsed}")

    def _reset_buttons(self):
        self.start_button.set_enabled(True)
        self.stop_button.set_enabled(False)

    def _show_counters(self, stats: dict):
        """Paint the request counters — including back to zero.

        Always written, never only-when-nonzero: a new crawl has to clear
        the last one's totals, or the bar reports a run that already
        finished.
        """
        requests = stats.get("requests", 0)
        failures = stats.get("failures", 0)
        self.request_label.configure(text=f"Requests: {requests:,}")
        self.failed_label.configure(text=f"Failed: {failures:,}",
                                    fg=t.RED if failures else t.FG_DIM)

    def _draw_progress(self, fraction: float):
        bar = self.progress_bar
        bar.delete("all")
        width = bar.winfo_width()
        if fraction <= 0 or width < 2:
            return
        bar.create_rectangle(0, 0, width * min(1.0, fraction), 3,
                             fill=t.ACCENT, outline="")

    # ------------------------------------------------------------------
    # files
    # ------------------------------------------------------------------
    def load_sample(self):
        self._supersede_pending_load()
        from . import demo        # pulls in the HTTP stack; not needed to open
        self.set_results(demo.sample_results(), sample=True)
        self.set_status(
            "Loaded a sample result set — invented listings, real scoring "
            "model. Press Start Scraping for live data.", t.AMBER)

    def load_results_file(self, path: Path) -> bool:
        from .. import persist
        try:
            scored = persist.load_results(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.set_status(f"Could not read {path}: {exc}", t.RED)
            return False
        self.set_results(scored, sample=False, source=Path(path))
        self.set_status(f"Loaded {len(scored):,} saved events from {path}.",
                        t.GREEN)
        return True

    def load_results_in_background(self, path: Path):
        """Read a results file on a worker thread, then show it.

        Anything that replaces the results meanwhile (a scrape, the sample
        set, Clear) supersedes the load, so a slow read never clobbers
        newer data.
        """
        from .. import persist
        path = Path(path)
        self._load_token += 1
        token = self._load_token
        if paths.is_cloud_placeholder(path):
            self.set_status(
                f"Downloading your saved results from iCloud ({path.name})… "
                "the app is usable meanwhile.", t.AMBER)
        else:
            self.set_status(f"Loading saved results from {path}…", t.FG)

        def work():
            try:
                outcome: Any = persist.load_results(path)
            except Exception as exc:          # noqa: BLE001 - shown to user
                outcome = exc
            self._loads.put((token, path, outcome))

        self._loads_in_flight += 1
        threading.Thread(target=work, name="load-results", daemon=True).start()
        self._pump_now()

    def _supersede_pending_load(self):
        self._load_token += 1

    def _drain_loads(self):
        while True:
            try:
                token, path, outcome = self._loads.get_nowait()
            except queue.Empty:
                return
            self._loads_in_flight = max(0, self._loads_in_flight - 1)
            if token != self._load_token:
                continue                      # replaced by newer results
            self._load_token += 1
            if isinstance(outcome, Exception):
                self.set_status(f"Could not read {path}: {outcome}", t.RED)
                continue
            self.set_results(outcome, sample=False, source=path)
            self.set_status(
                f"Loaded {len(outcome):,} saved events from {path}.", t.GREEN)

    def _autoload_last_results(self):
        saved = scrape.default_results_path(self.output_dir)
        if saved.is_file():
            self.load_results_in_background(saved)
        else:
            self.set_status("Ready to scrape.")

    def _open_results(self):
        chosen = filedialog.askopenfilename(
            title="Open saved results",
            initialdir=str(self.output_dir),
            filetypes=[("Saved results", "*.json"), ("All files", "*.*")],
        )
        if chosen:
            self.load_results_in_background(Path(chosen))

    def _save_results_as(self):
        from .. import persist
        if not self.all_rows:
            self.set_status("Nothing to save yet.", t.AMBER)
            return
        chosen = filedialog.asksaveasfilename(
            title="Save results", defaultextension=".json",
            initialdir=str(self.output_dir), initialfile="results.json",
            filetypes=[("Saved results", "*.json")],
        )
        if not chosen:
            return
        persist.save_results([r.scored for r in self.all_rows], Path(chosen))
        self.set_status(f"Saved {len(self.all_rows):,} events to {chosen}.",
                        t.GREEN)

    def _export_all(self):
        if not self.rows:
            self.set_status("Nothing to export yet.", t.AMBER)
            return
        self.tabs.select("export")
        written = self.export_panel.export()
        if written:
            self.set_status(f"Exported {len(written)} file(s) to "
                            f"{self.export_panel.folder.get()}.", t.GREEN)

    # ------------------------------------------------------------------
    # settings persistence
    # ------------------------------------------------------------------
    def gather_settings(self) -> dict:
        return {
            "version": __version__,
            "keyword": self.keyword.get(),
            "location": self.location.get(),
            "country": self.country.get(),
            "state": self.state.get(),
            "event_type": self.event_type.get(),
            "date_from": self.date_from.get(),
            "date_to": self.date_to.get(),
            "min_attendance": self.min_attendance.get(),
            "max_attendance": self.max_attendance.get(),
            "use_dates": self.use_dates.get(),
            "use_location": self.use_location.get(),
            "exact_match": self.exact_match.get(),
            "include_past": self.include_past.get(),
            "all_pages": self.all_pages.get(),
            "delay": self.delay.get(),
            "jobs": self.jobs.get(),
            "drive_hours": self.drive_hours.get(),
            "retry_failed": self.retry_failed.get(),
            "scrape_details": self.scrape_details.get(),
            "geocode": self.geocode.get(),
            "include_contact": self.include_contact.get(),
            "include_fees": self.include_fees.get(),
            "refresh_cache": self.refresh_cache.get(),
            "rank": self.rank.value,
            "columns": self.columns_button.ordered(),
            "page_size": self.page_size,
            "output_dir": str(self.output_dir),
            "geometry": self.winfo_geometry(),
        }

    def apply_settings(self, data: dict):
        text_fields = {
            "keyword": self.keyword, "location": self.location,
            "date_from": self.date_from, "date_to": self.date_to,
            "min_attendance": self.min_attendance,
            "max_attendance": self.max_attendance,
            "delay": self.delay, "jobs": self.jobs,
            "drive_hours": self.drive_hours,
        }
        for key, widget in text_fields.items():
            if isinstance(data.get(key), str):
                widget.set(data[key])
        checks = {
            "use_dates": self.use_dates, "use_location": self.use_location,
            "exact_match": self.exact_match, "include_past": self.include_past,
            "all_pages": self.all_pages, "retry_failed": self.retry_failed,
            "scrape_details": self.scrape_details, "geocode": self.geocode,
            "include_contact": self.include_contact,
            "include_fees": self.include_fees,
            "refresh_cache": self.refresh_cache,
        }
        for key, box in checks.items():
            if key in data:
                box.set(bool(data[key]))
        if data.get("country") in places.COUNTRIES:
            self.country.set(data["country"])
            self.state.set_options(self._state_options(data["country"]),
                                   vm.ALL_STATES, notify=False)
        if isinstance(data.get("state"), str):
            self.state.set(data["state"])
        if isinstance(data.get("event_type"), str):
            self.event_type.set(data["event_type"])
        if data.get("rank") in vm.SORT_LABELS:
            self.sort_order = data["rank"]
            self.rank.select(data["rank"], notify=False)
            self.sorted_by.set(data["rank"])
        columns = [k for k in data.get("columns", []) if k in vm.COLUMN_BY_KEY]
        if columns:
            self.columns_button.selected = columns
            self.grid_view.set_columns(columns)
        if data.get("page_size") in vm.PAGE_SIZES:
            self.page_size = data["page_size"]
            self.page_size_select.set(str(self.page_size))
        if isinstance(data.get("output_dir"), str):
            self._set_output_dir(Path(data["output_dir"]))
        if isinstance(data.get("geometry"), str):
            try:
                self.geometry(data["geometry"])
            except tk.TclError:
                pass
        self._refresh(reset_page=True)

    def _restore_settings(self):
        path = paths.settings_file()
        if not path.is_file():
            return
        try:
            self.apply_settings(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, tk.TclError) as exc:
            self.set_status(f"Ignoring unreadable settings file: {exc}", t.AMBER)

    def _persist_settings(self):
        path = paths.settings_file()
        try:
            paths.ensure(path.parent)
            path.write_text(json.dumps(self.gather_settings(), indent=2),
                            encoding="utf-8")
        except OSError:
            pass          # never block quitting over a settings file

    def _save_settings_as(self):
        chosen = filedialog.asksaveasfilename(
            title="Save settings", defaultextension=".json",
            initialfile="fnscraper-settings.json",
            initialdir=str(self.output_dir),
            filetypes=[("Settings", "*.json")],
        )
        if not chosen:
            return
        Path(chosen).write_text(json.dumps(self.gather_settings(), indent=2),
                                encoding="utf-8")
        self.set_status(f"Settings saved to {chosen}.", t.GREEN)

    def _load_settings_from(self):
        chosen = filedialog.askopenfilename(
            title="Load settings", initialdir=str(self.output_dir),
            filetypes=[("Settings", "*.json"), ("All files", "*.*")],
        )
        if not chosen:
            return
        try:
            self.apply_settings(json.loads(Path(chosen).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            messagebox.showerror(paths.APP_NAME, f"Could not load settings:\n{exc}")
            return
        self.set_status(f"Settings loaded from {chosen}.", t.GREEN)

    # ------------------------------------------------------------------
    def _about(self):
        messagebox.showinfo(
            paths.APP_NAME,
            f"{paths.APP_NAME} {__version__}\n\n"
            "Finds craft, art and food shows worth booking, scores them on "
            "what they should pay after fuel, lodging and booth fees, and "
            "exports the shortlist.\n\n"
            f"Home base: {config.HOME_NAME}\n"
            f"Business: {config.BUSINESS_NAME}\n"
            f"Data folder: {self.output_dir}",
        )

    def _on_close(self):
        if self.controller.running:
            if not messagebox.askokcancel(
                    paths.APP_NAME,
                    "A scrape is still running. Stop it and quit?"):
                return
            self.controller.stop()
        self._persist_settings()
        self.destroy()

    def destroy(self):
        for job in (self._refresh_job, self._pump_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._refresh_job = self._pump_job = None
        super().destroy()


_STAGE_LABELS = {
    "login": "Signing in",
    "crawl": "Crawling listings",
    "filter": "Filtering",
    "geocode": "Locating cities",
    "detail": "Reading event pages",
    "score": "Scoring",
    "save": "Saving",
}


def _elide_path(path: Path, limit: int = 52) -> str:
    """Keep the tail of a long path — the end is the part that identifies it.

    The status bar shares its row with the request counters, and an
    installed app's data folder is nested deep enough to push them off the
    window.
    """
    text = str(path)
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1):]


def _parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(text: str) -> int | None:
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None

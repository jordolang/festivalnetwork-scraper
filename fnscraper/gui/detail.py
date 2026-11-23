"""The detail pane under the results table.

One event at a time, in the order someone actually asks questions about a
show: where and when, then what it will cost, then who to call.
"""

from __future__ import annotations

import dataclasses
import tkinter as tk
import webbrowser
from datetime import date

from .. import config
from . import theme as t
from .viewmodel import Row, format_value, unit_name
from .widgets import Deck, ScrollFrame, TabBar, bind_wheel

TABS = (
    ("overview", "Overview"),
    ("schedule", "Schedule"),
    ("venue", "Venue"),
    ("financials", "Financials"),
    ("fees", "Fees & Deadlines"),
    ("contact", "Contact / Promoter"),
    ("notes", "Scoring Notes"),
    ("raw", "All Fields"),
)


def _money(value, estimated: bool = False) -> str:
    text = format_value("money2", value)
    return f"~{text}" if estimated and text != "—" else text


class DetailPane(tk.Frame):
    def __init__(self, parent: tk.Misc, **kw):
        super().__init__(parent, bg=t.BG, highlightthickness=1,
                         highlightbackground=t.BORDER, **kw)
        self.row: Row | None = None

        head = tk.Frame(self, bg=t.BG)
        head.pack(fill="x")
        self.title = tk.Label(head, text="No festival selected", bg=t.BG,
                              fg=t.FG, font=t.UI_TITLE, anchor="w")
        self.title.pack(side="left", padx=16, pady=(12, 6))
        self.badge = tk.Label(head, text="", bg=t.BG, fg=t.FG_MUTED,
                              font=t.UI_SMALL, anchor="w")
        self.badge.pack(side="left", padx=(4, 0), pady=(12, 6))

        self.tabs = TabBar(self, TABS, self._show, bg=t.BG, padx=12, pady=7)
        self.tabs.pack(fill="x", padx=8)
        tk.Frame(self, bg=t.BORDER_SOFT, height=1).pack(fill="x")

        self.deck = Deck(self, bg=t.BG)
        self.deck.pack(fill="both", expand=True)
        self._bodies: dict[str, ScrollFrame] = {}
        for key, _label in TABS:
            page = self.deck.page(key)
            body = ScrollFrame(page, bg=t.BG)
            body.pack(fill="both", expand=True)
            self._bodies[key] = body
        self.deck.show("overview")
        # Labels that wrap, with the fraction of the pane's width each one
        # gets.  Wrapping is driven from here — a label that sets its own
        # wraplength from its own <Configure> feeds its new size back into
        # the grid that produced it, and the two never agree.
        self._wrapped: list[tuple[tk.Label, float, int]] = []
        self._last_width = 0
        # Tabs drawn for the current row.  Only the tab on screen is built
        # when the selection changes; the others are built if opened.
        self._built: set[str] = set()
        self.bind("<Configure>", self._on_resize)
        self.show_empty()

    def _register_wrap(self, label: tk.Label, fraction: float, inset: int = 24):
        self._wrapped.append((label, fraction, inset))
        self._apply_wrap(label, fraction, inset)

    def _wrap_registrar(self, fraction: float, inset: int = 34):
        """A ``register`` callback bound to one column width."""
        return lambda label: self._register_wrap(label, fraction, inset)

    def _apply_wrap(self, label: tk.Label, fraction: float, inset: int):
        width = self._last_width or self.winfo_width() or 1200
        wrap = max(150, int(width * fraction) - inset)
        if int(label.cget("wraplength")) != wrap:
            label.configure(wraplength=wrap)

    def _on_resize(self, event):
        # Only a real change in the pane's own width re-wraps anything.
        if abs(event.width - self._last_width) < 8:
            return
        self._last_width = event.width
        for label, fraction, inset in self._wrapped:
            self._apply_wrap(label, fraction, inset)

    # -- public --------------------------------------------------------
    def set_row(self, row: Row | None):
        self.row = row
        if row is None:
            self.show_empty()
            return
        event = row.event
        self.title.configure(text=event.name)
        where = ", ".join(x for x in (event.city, event.state) if x)
        self.badge.configure(text=f"— {where}  ·  {row.text('dates')}")
        self._render()

    def show_empty(self):
        self.title.configure(text="No festival selected")
        self.badge.configure(text="— pick a row above to see everything "
                                  "the scraper found")
        self._built.clear()
        for body in self._bodies.values():
            for child in body.body.winfo_children():
                child.destroy()

    # -- rendering -----------------------------------------------------
    def _show(self, key: str):
        if self.row is not None:
            self._build(key)
        self.deck.show(key)

    def _render(self):
        """A new row: clear every tab, then draw just the visible one."""
        self._wrapped.clear()
        self._last_width = self.winfo_width()
        self._built.clear()
        for key, _label in TABS:
            for child in self._bodies[key].body.winfo_children():
                child.destroy()
        self._show(self.tabs.active)

    def _build(self, key: str):
        if key in self._built:
            return
        self._built.add(key)
        body = self._bodies[key].body
        getattr(self, f"_build_{key}")(body)
        self._bodies[key].bind_wheel_to(body)

    # -- individual tabs -----------------------------------------------
    def _build_overview(self, parent: tk.Frame):
        row, event, breakdown = self.row, self.row.event, self.row.breakdown
        grid = tk.Frame(parent, bg=t.BG)
        grid.pack(fill="both", expand=True, padx=16, pady=12)
        for index, weight in enumerate((0, 1, 1, 1)):
            grid.columnconfigure(index, weight=weight, uniform="detail")

        left = tk.Frame(grid, bg=t.BG)
        left.grid(row=0, column=0, sticky="nw", padx=(0, 24))
        _fields(left, [
            ("Location", ", ".join(x for x in (event.city, event.state) if x) or "—"),
            ("Dates", row.text("dates")),
            ("Event Type", row.get("category")),
            ("Attendance", row.text("attendance")),
            ("Exhibitors", row.text("exhibitors")),
            ("Admission", event.admission or "—"),
            ("Juried", event.juried or "—"),
            ("Drive time", row.text("drive_hours")),
            ("Booth fee", _money(breakdown.booth_fee, breakdown.booth_fee_estimated)),
            ("Est. revenue", _money(breakdown.gross_revenue)),
            ("Est. profit", _money(breakdown.est_profit)),
            ("Overall score", row.text("overall")),
        ])
        _link(left, "Open listing on festivalnet.com", event.url)

        middle = tk.Frame(grid, bg=t.BG)
        middle.grid(row=0, column=1, sticky="nsew", padx=(0, 16))
        quarter = self._wrap_registrar(0.25)
        _textbox(middle, "Description", event.description or
                 "This listing published no description.", register=quarter)
        notes = list(breakdown.notes)
        if event.unconfirmed_date:
            notes.append("the listing's dates are marked unconfirmed")
        if event.stale_listing:
            notes.append("the listing looks stale — verify it is running")
        _textbox(middle, "Notes",
                 "\n".join(f"• {n}" for n in notes) or "No caveats on this one.",
                 register=quarter)

        right = tk.Frame(grid, bg=t.BG)
        right.grid(row=0, column=2, sticky="nsew", padx=(0, 16))
        days = event.open_dates()
        schedule = [f"{d:%a %b} {d.day}" for d in days[:8]]
        if len(days) > 8:
            schedule.append(f"…and {len(days) - 8} more")
        _list_card(right, "Show days you would work",
                   schedule or ["Dates not published"], register=quarter)

        far_right = tk.Frame(grid, bg=t.BG)
        far_right.grid(row=0, column=3, sticky="nsew")
        unit = unit_name()
        _list_card(far_right, "Money at a glance", [
            f"Booth fee: {_money(breakdown.booth_fee, breakdown.booth_fee_estimated)}",
            f"Travel + lodging: {_money(breakdown.total_cost - breakdown.booth_fee)}",
            f"Out of pocket: {_money(breakdown.total_cost)}",
            f"Gross revenue: {_money(breakdown.gross_revenue)}",
            f"Cost of goods: {_money(breakdown.cogs)}",
            f"Profit: {_money(breakdown.est_profit)}",
            f"Return per dollar: {breakdown.roi:,.2f}",
            f"{unit.capitalize()}s sold (est.): {breakdown.jars_sold:,.0f}",
        ], register=quarter)

    def _build_schedule(self, parent: tk.Frame):
        event = self.row.event
        days = event.running_dates()
        open_days = event.open_dates()
        weekdays = event.open_weekdays()
        names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        _fields(body, [
            ("Start", _date(event.start_date)),
            ("End", _date(event.end_date)),
            ("Published hours", event.hours_text or "—"),
            ("Calendar days", f"{len(days):,}"),
            ("Days open", f"{len(open_days):,}"),
            ("Open weekdays", ", ".join(names[d] for d in sorted(weekdays))
             if weekdays else "runs straight through"),
            ("Days you would work", f"{event.occurrence_days():,}"),
            ("Schedule read from", _SCHEDULE_SOURCE.get(
                event.schedule_source(), event.schedule_source())),
        ])
        _list_card(body, "Every open day",
                   [f"{d:%A, %B} {d.day}, {d.year}" for d in open_days] or
                   ["No dates published"], pady=(14, 0),
                   register=self._wrap_registrar(0.9))

    def _build_venue(self, parent: tk.Frame):
        event = self.row.event
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        _fields(body, [
            ("Venue", event.venue or "—"),
            ("Address", event.address or "—"),
            ("City", event.city or "—"),
            ("State", event.state or "—"),
            ("ZIP", event.zip_code or "—"),
            ("Coordinates", f"{event.lat:.4f}, {event.lon:.4f}"
             if event.lat is not None else "not geocoded"),
            ("Distance", format_value("int", event.distance_miles) + " mi"
             if event.distance_miles else "—"),
            ("Drive time", self.row.text("drive_hours")),
            ("Home base", f"{config.HOME_NAME}"),
        ])
        if event.lat is not None:
            _link(body, "Open in your map app",
                  f"https://www.openstreetmap.org/?mlat={event.lat}"
                  f"&mlon={event.lon}#map=13/{event.lat}/{event.lon}")

    def _build_financials(self, parent: tk.Frame):
        b = self.row.breakdown
        unit = unit_name()
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        columns = tk.Frame(body, bg=t.BG)
        columns.pack(fill="both", expand=True)
        left = tk.Frame(columns, bg=t.BG)
        left.pack(side="left", anchor="n", padx=(0, 40))
        right = tk.Frame(columns, bg=t.BG)
        right.pack(side="left", anchor="n")
        _fields(left, [
            ("Attendance used", format_value("int", b.est_attendance)
             + (" (estimated)" if b.attendance_estimated else "")),
            ("Exhibitors used", format_value("int", b.est_exhibitors)
             + (" (estimated)" if b.exhibitors_estimated else "")),
            ("Category fit", f"x{b.category_fit:.2f}"),
            ("Competition factor", f"x{b.competition_factor:.2f}"),
            ("Admission factor", f"x{b.admission_factor:.2f}"),
            ("Data-quality factor", f"x{b.quality_factor:.2f}"),
            ("Estimated buyers", f"{b.est_buyers:,.0f}"),
            (f"{unit.capitalize()}s sold", f"{b.jars_sold:,.0f}"),
        ], title="How the crowd was sized")
        _fields(right, [
            ("Gross revenue", _money(b.gross_revenue)),
            ("Cost of goods", _money(b.cogs)),
            ("Booth fee", _money(b.booth_fee, b.booth_fee_estimated)),
            ("Fuel", _money(b.fuel_cost)),
            ("Lodging", _money(b.lodging_cost)),
            ("Meals", _money(b.meals_cost)),
            ("Total out of pocket", _money(b.total_cost)),
            ("Estimated profit", _money(b.est_profit)),
            ("Return per dollar", f"{b.roi:,.2f}"),
            (f"Cost per {unit}", _money(b.cost_per_jar)),
            ("Ranking score", f"{b.score:,.0f}"),
        ], title="What it pays")

    def _build_fees(self, parent: tk.Frame):
        event, b = self.row.event, self.row.breakdown
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        _fields(body, [
            ("Booth fee used", _money(b.booth_fee, b.booth_fee_estimated)),
            ("Source", "estimated from attendance tier"
             if b.booth_fee_estimated else "read from the listing"),
            ("Exhibitor fee", _money(event.exhib_fee)),
            ("Food-booth fee", _money(event.food_fee)),
            ("Fee as listed", event.booth_fee_text or "—"),
            ("Application deadline", self.row.get("deadline")),
            ("Exhibit deadline", event.exhibit_deadline or "—"),
            ("Food deadline", event.food_deadline or "—"),
            ("Deadlines (raw)", event.deadlines or "—"),
        ])
        _textbox(body, "How to apply", register=self._wrap_registrar(0.9),
                 text=event.application_info or
                 "The listing did not say how to apply. A FestivalNet Pro "
                 "login usually exposes this field.")
        if not event.pro_data:
            _note(body, "Signed out of FestivalNet Pro, so fees come from the "
                        "attendance-tier estimate rather than the promoter.")

    def _build_contact(self, parent: tk.Frame):
        event = self.row.event
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        _fields(body, [
            ("Promoter", event.promoter or "—"),
            ("Contact", event.contact_name or "—"),
            ("Email", event.contact_email or "—"),
            ("Phone", event.contact_phone or "—"),
        ])
        if event.promoter_website:
            _link(body, event.promoter_website, event.promoter_website)
        _link(body, "FestivalNet listing", event.url)
        if not any((event.contact_name, event.contact_email, event.contact_phone)):
            _note(body, "No contact details were collected. They live behind "
                        "FestivalNet's Pro login, and the rail's "
                        "“Scrape contact information” switch can "
                        "drop them on purpose.")

    def _build_notes(self, parent: tk.Frame):
        b, event = self.row.breakdown, self.row.event
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        notes = list(b.notes)
        if event.unconfirmed_date:
            notes.append("dates are flagged unconfirmed on the listing")
        if event.stale_listing:
            notes.append("the listing looks stale")
        _list_card(body, "What the model had to assume",
                   notes or ["Nothing was assumed — every input came from "
                             "the listing."],
                   register=self._wrap_registrar(0.9))
        _textbox(body, "How the score is built",
                 register=self._wrap_registrar(0.9),
                 text="score = profit x sqrt(return per dollar).\n"
                 "Profit rewards big shows; the square root of return "
                 "tilts the ranking toward shows that pay back the most "
                 "per dollar risked. A show that loses money scores "
                 "negative and sinks.")

    def _build_raw(self, parent: tk.Frame):
        body = tk.Frame(parent, bg=t.BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        pairs = []
        for field in dataclasses.fields(self.row.event):
            value = getattr(self.row.event, field.name)
            pairs.append((field.name, _plain(value)))
        _fields(body, pairs, title="Event", columns=2)
        pairs = []
        for field in dataclasses.fields(self.row.breakdown):
            value = getattr(self.row.breakdown, field.name)
            pairs.append((field.name, _plain(value)))
        _fields(body, pairs, title="Score breakdown", columns=2,
                pady=(16, 0))


_SCHEDULE_SOURCE = {
    "hours": "the listing's published hours",
    "text": "the name/description, not the hours",
    "assumed": "assumed Fri-Sun (nothing published)",
    "continuous": "runs straight through",
}


def _plain(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        return "; ".join(str(v) for v in value) or "—"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _date(value: date | None) -> str:
    return f"{value:%A, %B} {value.day}, {value.year}" if value else "—"


def _fields(parent: tk.Misc, pairs, *, title: str | None = None,
            columns: int = 1, pady=(0, 0)) -> tk.Frame:
    holder = tk.Frame(parent, bg=t.BG)
    holder.pack(fill="x", anchor="nw", pady=pady)
    if title:
        tk.Label(holder, text=title, bg=t.BG, fg=t.FG_DIM,
                 font=t.UI_TINY_BOLD, anchor="w").pack(anchor="w", pady=(0, 6))
    grid = tk.Frame(holder, bg=t.BG)
    grid.pack(fill="x", anchor="nw")
    per_column = -(-len(pairs) // columns)
    for index, (label, value) in enumerate(pairs):
        column = index // per_column if columns > 1 else 0
        line = index % per_column if columns > 1 else index
        tk.Label(grid, text=label, bg=t.BG, fg=t.FG_MUTED, font=t.UI_SMALL,
                 anchor="w").grid(row=line, column=column * 2, sticky="w",
                                  padx=(0, 12), pady=1)
        tk.Label(grid, text=value, bg=t.BG, fg=t.FG, font=t.UI_SMALL,
                 anchor="w", justify="left", wraplength=210).grid(
            row=line, column=column * 2 + 1, sticky="w", padx=(0, 28), pady=1)
    return holder


def _textbox(parent: tk.Misc, title: str, text: str, register=None) -> tk.Frame:
    holder = tk.Frame(parent, bg=t.BG)
    holder.pack(fill="x", anchor="nw", pady=(0, 12))
    tk.Label(holder, text=title, bg=t.BG, fg=t.FG_DIM, font=t.UI_TINY_BOLD,
             anchor="w").pack(anchor="w", pady=(0, 5))
    box = tk.Frame(holder, bg=t.BG_CARD, highlightthickness=1,
                   highlightbackground=t.BORDER)
    box.pack(fill="x")
    label = tk.Label(box, text=text, bg=t.BG_CARD, fg=t.FG, font=t.UI_SMALL,
                     anchor="nw", justify="left", wraplength=260)
    label.pack(fill="x", padx=10, pady=8)
    if register:
        register(label)
    return holder


def _list_card(parent: tk.Misc, title: str, items, pady=(0, 12),
               register=None) -> tk.Frame:
    holder = tk.Frame(parent, bg=t.BG)
    holder.pack(fill="x", anchor="nw", pady=pady)
    tk.Label(holder, text=title, bg=t.BG, fg=t.FG_DIM, font=t.UI_TINY_BOLD,
             anchor="w").pack(anchor="w", pady=(0, 5))
    box = tk.Frame(holder, bg=t.BG_CARD, highlightthickness=1,
                   highlightbackground=t.BORDER)
    box.pack(fill="x")
    inner = tk.Frame(box, bg=t.BG_CARD)
    inner.pack(fill="x", padx=10, pady=8)
    for item in items:
        line = tk.Frame(inner, bg=t.BG_CARD)
        line.pack(fill="x", pady=1)
        tk.Label(line, text="•", bg=t.BG_CARD, fg=t.ACCENT_TEXT,
                 font=t.UI_SMALL).pack(side="left", padx=(0, 6), anchor="n")
        text = tk.Label(line, text=item, bg=t.BG_CARD, fg=t.FG,
                        font=t.UI_SMALL, anchor="w", justify="left",
                        wraplength=240)
        text.pack(side="left", fill="x", expand=True)
        if register:
            register(text)
    return holder


def _link(parent: tk.Misc, text: str, url: str) -> tk.Label:
    label = tk.Label(parent, text=text, bg=t.BG, fg=t.ACCENT_TEXT,
                     font=t.UI_SMALL, cursor="hand2", anchor="w")
    label.pack(anchor="w", pady=(8, 0))
    label.bind("<Button-1>", lambda _e: webbrowser.open(url))
    label.bind("<Enter>", lambda _e: label.configure(
        font=(t.UI_SMALL[0], t.UI_SMALL[1], "underline")))
    label.bind("<Leave>", lambda _e: label.configure(font=t.UI_SMALL))
    return label


def _note(parent: tk.Misc, text: str) -> tk.Label:
    label = tk.Label(parent, text=text, bg=t.BG, fg=t.FG_DIM, font=t.UI_SMALL,
                     anchor="w", justify="left", wraplength=520)
    label.pack(anchor="w", pady=(12, 0))
    return label

"""Hand-drawn dark-theme controls.

ttk's native themes on macOS refuse to take a background colour, and its
Treeview cannot colour one cell differently from its neighbours — which
this app's green score columns need.  So the controls the window is built
from are assembled here out of frames, labels and canvases, which look and
behave identically on all three platforms.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable, Sequence

from . import icons, theme as t


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def bind_tree(widget: tk.Misc, sequence: str, handler) -> None:
    """Bind on a widget and every child, so labels don't swallow clicks."""
    widget.bind(sequence, handler)
    for child in widget.winfo_children():
        bind_tree(child, sequence, handler)


def bind_wheel(widget: tk.Misc, handler: Callable[[int], None]) -> None:
    """Normalise the three platforms' wheel events into ±1 steps."""
    def on_wheel(event):
        if getattr(event, "num", None) == 4:
            handler(-1)
        elif getattr(event, "num", None) == 5:
            handler(1)
        else:
            delta = event.delta
            # Windows reports 120 per notch; macOS reports small integers.
            step = -1 if delta > 0 else 1
            handler(step * max(1, min(3, abs(delta) // 120 or 1)))
        return "break"

    widget.bind("<MouseWheel>", on_wheel, add="+")
    widget.bind("<Button-4>", on_wheel, add="+")
    widget.bind("<Button-5>", on_wheel, add="+")


def hline(parent: tk.Misc, color: str = t.BORDER_SOFT, pady: int = 0) -> tk.Frame:
    line = tk.Frame(parent, bg=color, height=1)
    line.pack(fill="x", pady=pady)
    return line


def rounded(canvas: tk.Canvas, x0, y0, x1, y1, radius=6, **kw) -> int:
    """A rounded rectangle, since Tk's canvas only knows square ones."""
    radius = min(radius, abs(x1 - x0) / 2, abs(y1 - y0) / 2)
    points = [
        x0 + radius, y0, x1 - radius, y0, x1, y0, x1, y0 + radius,
        x1, y1 - radius, x1, y1, x1 - radius, y1, x0 + radius, y1,
        x0, y1, x0, y1 - radius, x0, y0 + radius, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


class Tooltip:
    """A one-line hint that follows the pointer after a short delay."""

    def __init__(self, widget: tk.Misc, text: str | Callable[[], str], delay: int = 450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after is not None:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text or self._tip is not None:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=t.BORDER)
        tk.Label(
            tip, text=text, bg=t.BG_POPUP, fg=t.FG, font=t.UI_SMALL,
            padx=8, pady=4, justify="left",
        ).pack(padx=1, pady=1)
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


# ---------------------------------------------------------------------------
# buttons
# ---------------------------------------------------------------------------

class FlatButton(tk.Frame):
    """A bordered button with an optional vector icon.

    ``kind`` picks the palette: ``default`` for the toolbar, ``primary``
    for Start Scraping, ``ghost`` for icon-only affordances like the pager.
    """

    def __init__(self, parent: tk.Misc, text: str = "", command=None, *,
                 icon: str | None = None, kind: str = "default",
                 icon_color: str | None = None, padx: int = 11, pady: int = 6,
                 font=None, width: int | None = None, **kw):
        self.kind = kind
        self.bg, self.hover_bg, self.fg, self.border = _button_palette(kind)
        super().__init__(
            parent, bg=self.bg, highlightthickness=1 if self.border else 0,
            highlightbackground=self.border or self.bg,
            highlightcolor=self.border or self.bg, cursor="hand2", **kw,
        )
        self.command = command
        self._enabled = True
        self._icon_name = icon
        self._icon_color = icon_color or (t.GREEN if kind == "primary" else t.FG_MUTED)

        box = tk.Frame(self, bg=self.bg)
        box.pack(padx=padx, pady=pady)
        self._box = box
        self._canvas = None
        if icon:
            self._canvas = tk.Canvas(
                box, width=15, height=15, bg=self.bg, highlightthickness=0,
                bd=0, takefocus=0,
            )
            self._canvas.pack(side="left", padx=(0, 7 if text else 0))
            self._paint_icon()
        self._label = None
        if text:
            self._label = tk.Label(
                box, text=text, bg=self.bg, fg=self.fg,
                font=font or t.UI_SMALL, width=width or 0,
            )
            self._label.pack(side="left")

        bind_tree(self, "<Enter>", self._on_enter)
        bind_tree(self, "<Leave>", self._on_leave)
        bind_tree(self, "<Button-1>", self._on_press)
        bind_tree(self, "<ButtonRelease-1>", self._on_release)

    # -- painting ------------------------------------------------------
    def _paint_icon(self):
        if self._canvas is None:
            return
        self._canvas.delete("all")
        color = self._icon_color if self._enabled else t.DISABLED
        icons.draw(self._canvas, self._icon_name, 0, 0, 15, color, 1.6)

    def _set_bg(self, bg: str):
        for widget in (self, self._box, self._label, self._canvas):
            if widget is not None:
                widget.configure(bg=bg)

    def configure_text(self, text: str):
        if self._label is not None:
            self._label.configure(text=text)

    def set_enabled(self, enabled: bool):
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if self._label is not None:
            self._label.configure(fg=self.fg if enabled else t.DISABLED)
        self.configure(cursor="hand2" if enabled else "arrow")
        self._set_bg(self.bg)
        self._paint_icon()

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- events --------------------------------------------------------
    def _on_enter(self, _event=None):
        if self._enabled:
            self._set_bg(self.hover_bg)

    def _on_leave(self, _event=None):
        self._set_bg(self.bg)

    def _on_press(self, _event=None):
        if self._enabled:
            self._set_bg(t.BG_BUTTON_HOVER)

    def _on_release(self, event=None):
        if not self._enabled:
            return
        self._on_enter()
        if self.command is not None:
            self.command()


def _button_palette(kind: str) -> tuple[str, str, str, str]:
    if kind == "primary":
        return t.BG_BUTTON, t.BG_BUTTON_HOVER, t.FG, t.BORDER_FOCUS
    if kind == "ghost":
        return t.BG, t.BG_BUTTON, t.FG_MUTED, ""
    if kind == "bar":
        return t.BG_BAR, t.BG_BUTTON, t.FG_MUTED, ""
    return t.BG_BUTTON, t.BG_BUTTON_HOVER, t.FG, t.BORDER


class IconButton(tk.Canvas):
    """A square icon-only button — pager arrows, popup close buttons."""

    def __init__(self, parent: tk.Misc, name: str, command=None, *,
                 size: int = 26, bg: str = t.BG, color: str = t.FG_MUTED,
                 hover_bg: str = t.BG_BUTTON, **kw):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self.name, self.command = name, command
        self.size, self.base_bg, self.hover_bg = size, bg, hover_bg
        self.color = color
        self._enabled = True
        self._paint()
        self.bind("<Enter>", lambda _e: self._enabled and self.configure(bg=self.hover_bg))
        self.bind("<Leave>", lambda _e: self.configure(bg=self.base_bg))
        self.bind("<Button-1>", self._click)

    def _paint(self):
        self.delete("all")
        pad = self.size * 0.28
        icons.draw(self, self.name, pad, pad, self.size - 2 * pad,
                   self.color if self._enabled else t.DISABLED, 1.6)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow", bg=self.base_bg)
        self._paint()

    def _click(self, _event=None):
        if self._enabled and self.command is not None:
            self.command()


# ---------------------------------------------------------------------------
# checkbox / radio
# ---------------------------------------------------------------------------

class CheckBox(tk.Frame):
    def __init__(self, parent: tk.Misc, text: str, value: bool = False,
                 command: Callable[[bool], None] | None = None, *,
                 bg: str = t.BG_SIDEBAR, font=None, **kw):
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self.var = tk.BooleanVar(value=value)
        self.command = command
        self._bg = bg
        self.box = tk.Canvas(self, width=15, height=15, bg=bg,
                             highlightthickness=0, bd=0, takefocus=0)
        self.box.pack(side="left", pady=1)
        self.label = tk.Label(self, text=text, bg=bg, fg=t.FG,
                              font=font or t.UI_SMALL, anchor="w",
                              justify="left")
        self.label.pack(side="left", padx=(7, 0))
        self._paint()
        bind_tree(self, "<Button-1>", self._toggle)

    def _paint(self):
        self.box.delete("all")
        on = self.var.get()
        fill = t.ACCENT if on else t.BG_INPUT
        outline = t.ACCENT if on else t.BORDER_FOCUS
        rounded(self.box, 1, 1, 14, 14, 3, fill=fill, outline=outline, width=1)
        if on:
            icons.draw(self.box, "check", 1.5, 1.5, 12, "#ffffff", 1.8)

    def get(self) -> bool:
        return self.var.get()

    def set(self, value: bool, notify: bool = False):
        self.var.set(bool(value))
        self._paint()
        if notify and self.command:
            self.command(self.var.get())

    def _toggle(self, _event=None):
        self.set(not self.var.get(), notify=True)


class RadioGroup:
    """Keeps a set of :class:`RadioItem` widgets in sync."""

    def __init__(self, value: str = "",
                 command: Callable[[str], None] | None = None):
        self.value = value
        self.command = command
        self.items: list[RadioItem] = []

    def register(self, item: "RadioItem"):
        self.items.append(item)

    def select(self, value: str, notify: bool = True):
        self.value = value
        for item in self.items:
            item.refresh()
        if notify and self.command:
            self.command(value)


class RadioItem(tk.Frame):
    def __init__(self, parent: tk.Misc, group: RadioGroup, value: str,
                 text: str, *, bg: str = t.BG_SIDEBAR, font=None, **kw):
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self.group, self.value = group, value
        self.dot = tk.Canvas(self, width=15, height=15, bg=bg,
                             highlightthickness=0, bd=0, takefocus=0)
        self.dot.pack(side="left", pady=1)
        self.label = tk.Label(self, text=text, bg=bg, fg=t.FG,
                              font=font or t.UI_SMALL, anchor="w")
        self.label.pack(side="left", padx=(7, 0))
        group.register(self)
        self.refresh()
        bind_tree(self, "<Button-1>", lambda _e: group.select(value))

    def refresh(self):
        on = self.group.value == self.value
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 14, 14, outline=t.ACCENT if on else t.BORDER_FOCUS,
                             width=1, fill=t.BG_INPUT)
        if on:
            self.dot.create_oval(4, 4, 11, 11, outline="", fill=t.ACCENT)
        self.label.configure(fg=t.FG if on else t.FG_MUTED)


# ---------------------------------------------------------------------------
# text entry
# ---------------------------------------------------------------------------

class TextField(tk.Frame):
    """A flat entry with placeholder text and an optional leading icon."""

    def __init__(self, parent: tk.Misc, *, placeholder: str = "",
                 value: str = "", icon: str | None = None,
                 on_change: Callable[[str], None] | None = None,
                 on_submit: Callable[[str], None] | None = None,
                 width: int = 10, bg: str = t.BG_INPUT, **kw):
        super().__init__(parent, bg=bg, highlightthickness=1,
                         highlightbackground=t.BORDER, highlightcolor=t.ACCENT,
                         **kw)
        self.placeholder = placeholder
        self.on_change = on_change
        self._showing_placeholder = False

        if icon:
            canvas = tk.Canvas(self, width=14, height=14, bg=bg,
                               highlightthickness=0, bd=0, takefocus=0)
            canvas.pack(side="left", padx=(7, 0))
            icons.draw(canvas, icon, 0, 0, 14, t.FG_DIM, 1.4)

        self.var = tk.StringVar(value=value)
        self.entry = tk.Entry(
            self, textvariable=self.var, bg=bg, fg=t.FG, font=t.UI_SMALL,
            insertbackground=t.FG, relief="flat", bd=0, width=width,
            highlightthickness=0, disabledbackground=bg,
            disabledforeground=t.DISABLED,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=7, pady=5)
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        if on_submit:
            self.entry.bind("<Return>", lambda _e: on_submit(self.get()))
        self.var.trace_add("write", self._changed)
        self._show_placeholder()

    # -- placeholder ---------------------------------------------------
    def _show_placeholder(self):
        if not self.placeholder or self.var.get():
            return
        self._showing_placeholder = True
        self.entry.configure(fg=t.FG_DIM)
        self.var.set(self.placeholder)

    def _clear_placeholder(self):
        if self._showing_placeholder:
            self._showing_placeholder = False
            self.var.set("")
            self.entry.configure(fg=t.FG)

    def _focus_in(self, _event=None):
        self._clear_placeholder()

    def _focus_out(self, _event=None):
        if not self.var.get():
            self._show_placeholder()

    def _changed(self, *_args):
        if self._showing_placeholder:
            return
        if self.on_change:
            self.on_change(self.get())

    # -- value ---------------------------------------------------------
    def get(self) -> str:
        return "" if self._showing_placeholder else self.var.get().strip()

    def set(self, value: str):
        self._showing_placeholder = False
        self.entry.configure(fg=t.FG)
        self.var.set(value)
        if not value:
            self._show_placeholder()

    def set_enabled(self, enabled: bool):
        self.entry.configure(state="normal" if enabled else "disabled")


class NumberField(TextField):
    """A TextField with a stepper, for delays and worker counts."""

    def __init__(self, parent: tk.Misc, *, value: float = 0, minimum: float = 0,
                 maximum: float = 999, step: float = 1, decimals: int = 0,
                 on_change: Callable[[str], None] | None = None, width: int = 5,
                 **kw):
        self.minimum, self.maximum, self.step = minimum, maximum, step
        self.decimals = decimals
        super().__init__(parent, value=self._fmt(value), width=width,
                         on_change=on_change, **kw)
        stepper = tk.Frame(self, bg=t.BG_INPUT)
        stepper.pack(side="right", padx=(0, 3))
        for name, delta in (("chevron-up", +1), ("chevron-down", -1)):
            arrow = tk.Canvas(stepper, width=13, height=9, bg=t.BG_INPUT,
                              highlightthickness=0, bd=0, cursor="hand2")
            arrow.pack()
            icons.draw(arrow, name, 0, -2, 13, t.FG_MUTED, 1.3)
            arrow.bind("<Button-1>", lambda _e, d=delta: self.bump(d))

    def _fmt(self, value: float) -> str:
        return f"{value:.{self.decimals}f}" if self.decimals else str(int(value))

    def value(self) -> float:
        try:
            return float(self.get())
        except ValueError:
            return self.minimum

    def bump(self, direction: int):
        new = min(self.maximum, max(self.minimum,
                                    self.value() + direction * self.step))
        self.set(self._fmt(new))


# ---------------------------------------------------------------------------
# popups: single-choice select and multi-choice checklist
# ---------------------------------------------------------------------------

class _Popup(tk.Toplevel):
    """A borderless list anchored under a widget, closed by clicking away."""

    def __init__(self, anchor: tk.Misc, width: int, max_height: int = 320):
        super().__init__(anchor)
        self.withdraw()
        self.wm_overrideredirect(True)
        try:                       # macOS: no shadow, no dock icon flicker
            self.tk.call("::tk::unsupported::MacWindowStyle", "style",
                         self._w, "help", "noActivates")
        except tk.TclError:
            pass
        self.configure(bg=t.BORDER)
        self.body = tk.Frame(self, bg=t.BG_POPUP)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self._width = width
        self._max_height = max_height
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Button-1>", self._maybe_close, add="+")

    def show_under(self, widget: tk.Misc, align: str = "left"):
        self.update_idletasks()
        height = min(self._max_height, self.body.winfo_reqheight() + 2)
        x = widget.winfo_rootx()
        if align == "right":
            x = widget.winfo_rootx() + widget.winfo_width() - self._width
        y = widget.winfo_rooty() + widget.winfo_height() + 3
        screen_h = self.winfo_screenheight()
        if y + height > screen_h:                 # flip above when it won't fit
            y = max(0, widget.winfo_rooty() - height - 3)
        self.wm_geometry(f"{self._width}x{height}+{max(0, x)}+{y}")
        self.deiconify()
        self.lift()
        self.grab_set()

    def _maybe_close(self, event):
        inside = (0 <= event.x <= self.winfo_width()
                  and 0 <= event.y <= self.winfo_height())
        if not inside:
            self.close()

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def _popup_row(parent: tk.Misc, text: str, command, *, checked: bool = False,
               check_style: str = "tick") -> tk.Frame:
    row = tk.Frame(parent, bg=t.BG_POPUP, cursor="hand2")
    row.pack(fill="x")
    mark = tk.Canvas(row, width=14, height=14, bg=t.BG_POPUP,
                     highlightthickness=0, bd=0, takefocus=0)
    mark.pack(side="left", padx=(9, 0), pady=5)
    if check_style == "box":
        rounded(mark, 0, 0, 13, 13, 3,
                fill=t.ACCENT if checked else t.BG_INPUT,
                outline=t.ACCENT if checked else t.BORDER_FOCUS, width=1)
        if checked:
            icons.draw(mark, "check", 0.5, 0.5, 12, "#ffffff", 1.7)
    elif checked:
        icons.draw(mark, "check", 0, 0, 14, t.ACCENT, 1.8)
    label = tk.Label(row, text=text, bg=t.BG_POPUP,
                     fg=t.FG if checked else t.FG_MUTED,
                     font=t.UI_SMALL, anchor="w")
    label.pack(side="left", fill="x", expand=True, padx=(6, 12))

    def hover(bg, fg):
        row.configure(bg=bg)
        mark.configure(bg=bg)
        label.configure(bg=bg, fg=fg)

    row.bind("<Enter>", lambda _e: hover(t.BG_ROW_HOVER, t.FG))
    label.bind("<Enter>", lambda _e: hover(t.BG_ROW_HOVER, t.FG))
    row.bind("<Leave>", lambda _e: hover(t.BG_POPUP, t.FG if checked else t.FG_MUTED))
    label.bind("<Leave>", lambda _e: hover(t.BG_POPUP, t.FG if checked else t.FG_MUTED))
    bind_tree(row, "<Button-1>", lambda _e: command())
    return row


class Select(tk.Frame):
    """A read-only dropdown: current value, chevron, popup list."""

    def __init__(self, parent: tk.Misc, options: Sequence[str] | Sequence[tuple[str, str]],
                 value: str | None = None,
                 on_change: Callable[[str], None] | None = None, *,
                 width: int = 180, bg: str = t.BG_INPUT, font=None, **kw):
        super().__init__(parent, bg=bg, highlightthickness=1,
                         highlightbackground=t.BORDER, highlightcolor=t.BORDER,
                         cursor="hand2", **kw)
        self.on_change = on_change
        self._width = width
        self.set_options(options, value, notify=False, redraw=False)

        self.label = tk.Label(self, text=self.label_for(self.value), bg=bg,
                              fg=t.FG, font=font or t.UI_SMALL, anchor="w")
        self.label.pack(side="left", fill="x", expand=True, padx=(9, 4), pady=5)
        self.arrow = tk.Canvas(self, width=14, height=14, bg=bg,
                               highlightthickness=0, bd=0, takefocus=0)
        self.arrow.pack(side="right", padx=(0, 7))
        icons.draw(self.arrow, "chevron-down", 0, 0, 14, t.FG_MUTED, 1.4)
        bind_tree(self, "<Button-1>", lambda _e: self.open())

    # -- options -------------------------------------------------------
    def set_options(self, options, value=None, notify=True, redraw=True):
        self.options: list[tuple[str, str]] = [
            (o, o) if isinstance(o, str) else tuple(o) for o in options
        ]
        keys = [key for key, _ in self.options]
        if value is None or value not in keys:
            value = self.options[0][0] if self.options else ""
        self.value = value
        if redraw:
            self.label.configure(text=self.label_for(value))
        if notify and self.on_change:
            self.on_change(value)

    def label_for(self, key: str) -> str:
        for option_key, label in self.options:
            if option_key == key:
                return label
        return key

    def get(self) -> str:
        return self.value

    def set(self, key: str, notify: bool = False):
        self.value = key
        self.label.configure(text=self.label_for(key))
        if notify and self.on_change:
            self.on_change(key)

    # -- popup ---------------------------------------------------------
    def open(self):
        popup = _Popup(self, max(self._width, self.winfo_width()))
        canvas_holder = _scroll_body(popup.body, self._width)
        for key, label in self.options:
            _popup_row(canvas_holder, label,
                       lambda k=key: (popup.close(), self.set(k, notify=True)),
                       checked=(key == self.value))
        popup.show_under(self)


class CheckListButton(FlatButton):
    """A button whose popup is a list of checkboxes (the Columns menu)."""

    def __init__(self, parent: tk.Misc, text: str,
                 options: Sequence[tuple[str, str]], selected: Iterable[str],
                 on_change: Callable[[list[str]], None] | None = None, *,
                 icon: str | None = "columns", width: int = 240, **kw):
        super().__init__(parent, text, self.open, icon=icon, **kw)
        self.options = list(options)
        self.selected = list(selected)
        self.on_change = on_change
        self._width = width
        self._trailer = tk.Canvas(self._box, width=13, height=13, bg=self.bg,
                                  highlightthickness=0, bd=0, takefocus=0)
        self._trailer.pack(side="left", padx=(7, 0))
        icons.draw(self._trailer, "chevron-down", 0, 0, 13, t.FG_MUTED, 1.4)
        bind_tree(self, "<Enter>", self._on_enter)
        bind_tree(self, "<Leave>", self._on_leave)
        bind_tree(self, "<ButtonRelease-1>", self._on_release)

    def _set_bg(self, bg: str):
        super()._set_bg(bg)
        if getattr(self, "_trailer", None) is not None:
            self._trailer.configure(bg=bg)

    def open(self):
        popup = _Popup(self, self._width, max_height=420)
        body = _scroll_body(popup.body, self._width)

        def toggle(key: str):
            if key in self.selected:
                if len(self.selected) > 1:
                    self.selected.remove(key)
            else:
                self.selected.append(key)
            for child in body.winfo_children():
                child.destroy()
            build()
            if self.on_change:
                self.on_change(self.ordered())

        def build():
            for key, label in self.options:
                _popup_row(body, label, lambda k=key: toggle(k),
                           checked=key in self.selected, check_style="box")

        build()
        popup.show_under(self, align="right")

    def ordered(self) -> list[str]:
        """Selected keys, in the options' own order — not click order."""
        return [key for key, _ in self.options if key in self.selected]


def _scroll_body(parent: tk.Misc, width: int) -> tk.Frame:
    """A vertically scrollable body for a popup that outgrows its screen."""
    canvas = tk.Canvas(parent, bg=t.BG_POPUP, highlightthickness=0, bd=0,
                       width=width - 2)
    canvas.pack(side="left", fill="both", expand=True)
    body = tk.Frame(canvas, bg=t.BG_POPUP)
    window = canvas.create_window((0, 0), window=body, anchor="nw", width=width - 2)

    def resize(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(window, width=canvas.winfo_width())

    body.bind("<Configure>", resize)
    canvas.bind("<Configure>", resize)
    bind_wheel(canvas, lambda step: canvas.yview_scroll(step, "units"))
    return body


# ---------------------------------------------------------------------------
# layout pieces
# ---------------------------------------------------------------------------

class SectionTitle(tk.Frame):
    def __init__(self, parent: tk.Misc, text: str, *, bg: str = t.BG_SIDEBAR,
                 caps: bool = False, **kw):
        super().__init__(parent, bg=bg, **kw)
        tk.Label(
            self, text=text.upper() if caps else text, bg=bg,
            fg=t.FG_DIM if caps else t.FG,
            font=t.UI_TINY_BOLD if caps else t.UI_BOLD, anchor="w",
        ).pack(side="left")


class FieldLabel(tk.Label):
    def __init__(self, parent: tk.Misc, text: str, *, bg: str = t.BG_SIDEBAR, **kw):
        super().__init__(parent, text=text, bg=bg, fg=t.FG_MUTED,
                         font=t.UI_SMALL, anchor="w", **kw)


class ScrollFrame(tk.Frame):
    """A frame that scrolls vertically when its content is too tall.

    The scrollbar is always packed, even with nothing to scroll (ttk draws
    a bare trough then).  Showing it on demand would be tidier, but it
    costs the content 11 pixels of width the moment it appears — and a
    panel of wrapped text gets *taller* when it gets narrower, which can
    push it back under the threshold, hide the bar, widen the content, and
    start again.  Reserving the width makes the layout a fixed point.
    """

    def __init__(self, parent: tk.Misc, *, bg: str = t.BG_SIDEBAR, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = t.scrollbar(self, "vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")
        self.body.bind("<Configure>", self._resize)
        self.canvas.bind("<Configure>", self._resize)
        bind_wheel(self.canvas, lambda step: self.canvas.yview_scroll(step, "units"))
        bind_wheel(self.body, lambda step: self.canvas.yview_scroll(step, "units"))

    def _resize(self, _event=None):
        region = self.canvas.bbox("all")
        if region and self.canvas.cget("scrollregion") != " ".join(
                str(v) for v in region):
            self.canvas.configure(scrollregion=region)
        width = self.canvas.winfo_width()
        if int(self.canvas.itemcget(self._window, "width") or 0) != width:
            self.canvas.itemconfigure(self._window, width=width)

    def bind_wheel_to(self, widget: tk.Misc):
        bind_wheel(widget, lambda step: self.canvas.yview_scroll(step, "units"))


class TabBar(tk.Frame):
    """The underlined tab strip used for both the results and detail panes."""

    def __init__(self, parent: tk.Misc, tabs: Sequence[tuple[str, str]],
                 on_change: Callable[[str], None] | None = None, *,
                 bg: str = t.BG, active: str | None = None,
                 font=None, padx: int = 14, pady: int = 8, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.on_change = on_change
        self._bg = bg
        self._font = font or t.UI_SMALL
        self._padx, self._pady = padx, pady
        self._tabs: dict[str, dict] = {}
        self.active = active or (tabs[0][0] if tabs else "")
        for key, label in tabs:
            self._add(key, label)
        self.refresh()

    def _add(self, key: str, label: str):
        holder = tk.Frame(self, bg=self._bg, cursor="hand2")
        holder.pack(side="left")
        text = tk.Label(holder, text=label, bg=self._bg, fg=t.FG_MUTED,
                        font=self._font)
        text.pack(padx=self._padx, pady=(self._pady, self._pady - 2))
        underline = tk.Frame(holder, bg=self._bg, height=2)
        underline.pack(fill="x")
        for widget in (holder, text):
            widget.bind("<Button-1>", lambda _e, k=key: self.select(k))
            widget.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
            widget.bind("<Leave>", lambda _e, k=key: self._hover(k, False))
        self._tabs[key] = {"holder": holder, "label": text, "line": underline}

    def _hover(self, key: str, entering: bool):
        if key == self.active:
            return
        self._tabs[key]["label"].configure(fg=t.FG if entering else t.FG_MUTED)

    def select(self, key: str, notify: bool = True):
        if key not in self._tabs:
            return
        self.active = key
        self.refresh()
        if notify and self.on_change:
            self.on_change(key)

    def refresh(self):
        for key, parts in self._tabs.items():
            on = key == self.active
            parts["label"].configure(fg=t.FG if on else t.FG_MUTED)
            parts["line"].configure(bg=t.ACCENT if on else self._bg)


class Deck(tk.Frame):
    """Holds one frame per tab and shows only the active one.

    Hidden pages are unmapped, not merely stacked underneath: a stacked
    page still gets every resize, and each of its canvases (map, calendar,
    charts, the full table) repainted on every step of a window drag.
    """

    def __init__(self, parent: tk.Misc, *, bg: str = t.BG, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.pages: dict[str, tk.Frame] = {}
        self.active: str | None = None
        self._bg = bg

    def page(self, key: str) -> tk.Frame:
        if key not in self.pages:
            self.pages[key] = tk.Frame(self, bg=self._bg)
        return self.pages[key]

    def show(self, key: str):
        shown = self.page(key)
        for other_key, frame in self.pages.items():
            if other_key != key:
                frame.place_forget()
        shown.place(relx=0, rely=0, relwidth=1, relheight=1)
        shown.lift()
        self.active = key


class StatCard(tk.Frame):
    """One of the six headline numbers across the top of the overview."""

    def __init__(self, parent: tk.Misc, value: str, label: str, icon: str,
                 accent: str = t.ACCENT_TEXT, **kw):
        super().__init__(parent, bg=t.BG_CARD, highlightthickness=1,
                         highlightbackground=t.BORDER, **kw)
        body = tk.Frame(self, bg=t.BG_CARD)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        text = tk.Frame(body, bg=t.BG_CARD)
        text.pack(side="left", fill="both", expand=True)
        self.value = tk.Label(text, text=value, bg=t.BG_CARD, fg=t.FG,
                              font=t.UI_BIG, anchor="w")
        self.value.pack(anchor="w")
        self.caption = tk.Label(text, text=label, bg=t.BG_CARD, fg=t.FG_MUTED,
                                font=t.UI_TINY, anchor="w", justify="left")
        self.caption.pack(anchor="w", pady=(3, 0))
        self.glyph = tk.Canvas(body, width=22, height=22, bg=t.BG_CARD,
                               highlightthickness=0, bd=0, takefocus=0)
        self.glyph.pack(side="right", anchor="n", padx=(6, 0))
        icons.draw(self.glyph, icon, 0, 0, 22, accent, 1.6)
        # Six cards across a narrow window leave the caption no room; wrap
        # it to whatever the card actually got rather than clipping it.
        self.caption.bind("<Configure>", self._wrap_caption)

    def _wrap_caption(self, event):
        wrap = max(60, event.width)
        if self.caption.cget("wraplength") != wrap:
            self.caption.configure(wraplength=wrap)

    def update_value(self, value: str, label: str | None = None):
        self.value.configure(text=value)
        if label is not None:
            self.caption.configure(text=label)


class Pager(tk.Frame):
    """First / prev / numbered pages / next / last."""

    def __init__(self, parent: tk.Misc, on_page: Callable[[int], None], *,
                 bg: str = t.BG, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.on_page = on_page
        self._bg = bg
        self.page = 1
        self.pages = 1

    def render(self, page: int, pages: int):
        from .viewmodel import page_numbers
        self.page, self.pages = page, pages
        for child in self.winfo_children():
            child.destroy()
        first = IconButton(self, "first", lambda: self.on_page(1), bg=self._bg)
        first.pack(side="left", padx=1)
        first.set_enabled(page > 1)
        prev = IconButton(self, "chevron-left", lambda: self.on_page(page - 1),
                          bg=self._bg)
        prev.pack(side="left", padx=1)
        prev.set_enabled(page > 1)

        for number in page_numbers(page, pages):
            if number is None:
                tk.Label(self, text="…", bg=self._bg, fg=t.FG_DIM,
                         font=t.UI_SMALL, width=2).pack(side="left", padx=1)
                continue
            active = number == page
            button = tk.Label(
                self, text=str(number), width=3, pady=4,
                bg=t.ACCENT if active else self._bg,
                fg="#ffffff" if active else t.FG_MUTED,
                font=t.UI_SMALL_BOLD if active else t.UI_SMALL, cursor="hand2",
            )
            button.pack(side="left", padx=1)
            if not active:
                button.bind("<Enter>", lambda _e, b=button: b.configure(
                    bg=t.BG_BUTTON, fg=t.FG))
                button.bind("<Leave>", lambda _e, b=button: b.configure(
                    bg=self._bg, fg=t.FG_MUTED))
            button.bind("<Button-1>", lambda _e, n=number: self.on_page(n))

        nxt = IconButton(self, "chevron-right", lambda: self.on_page(page + 1),
                         bg=self._bg)
        nxt.pack(side="left", padx=1)
        nxt.set_enabled(page < pages)
        last = IconButton(self, "last", lambda: self.on_page(pages), bg=self._bg)
        last.pack(side="left", padx=1)
        last.set_enabled(page < pages)

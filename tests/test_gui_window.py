"""End-to-end checks on the real window.

These need a display.  They are skipped when Tk is missing or no display
is reachable, so a headless checkout still runs the rest of the suite;
CI runs them under ``xvfb-run``.
"""

from __future__ import annotations

import json

import pytest

tkinter = pytest.importorskip("tkinter")

from fnscraper.gui import viewmodel as vm            # noqa: E402
from fnscraper.gui.detail import TABS as DETAIL_TABS  # noqa: E402


def test_selftest_survives_a_windowed_build_with_no_console(monkeypatch):
    """A GUI-subsystem binary can have sys.stdout/stderr set to None.

    CPython's print is a no-op on a None stream, so this never crashed —
    but the self-test's verdict has to survive having nowhere to print it,
    and that is worth pinning rather than rediscovering.
    """
    import sys

    from fnscraper import gui

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert gui.selftest() == 0


def test_selftest_still_fails_loudly_with_no_console(monkeypatch, tmp_path):
    """Silent output must not become a silent pass."""
    import sys

    from fnscraper import gui
    from fnscraper.gui import paths

    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert gui.selftest() == 1


def test_say_drops_output_rather_than_raising(monkeypatch):
    import io
    import sys

    from fnscraper import gui

    class Closed(io.StringIO):
        def write(self, _text):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(sys, "stdout", Closed())
    gui.say("this must not raise")
    monkeypatch.setattr(sys, "stdout", None)
    gui.say("nor this")


def test_the_packaged_app_selftest_passes_here():
    """The check CI runs against the frozen build, run against the source.

    Needs no display: it is the import graph and the bundled assets that
    packaging breaks, and both are checkable headless.
    """
    from fnscraper import gui

    assert gui.selftest() == 0


@pytest.fixture(scope="module")
def display_available() -> bool:
    try:
        probe = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"no display for Tk: {exc}")
    probe.destroy()
    return True


@pytest.fixture
def window(display_available, tmp_path, monkeypatch):
    """A window on sample data, writing anywhere but the user's home."""
    from fnscraper.gui import app as app_module, paths

    monkeypatch.setattr(paths, "default_output_dir", lambda: tmp_path / "out")
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(paths, "settings_file",
                        lambda: tmp_path / "settings.json")
    win = app_module.ScraperWindow(sample=True)
    win.update()
    yield win
    win.destroy()


def test_the_window_opens_on_the_sample_set(window):
    assert len(window.all_rows) > 20
    assert window.results_title.cget("text") == \
        f"Results ({len(window.rows):,} festivals)"
    assert window.sample_badge.cget("text").startswith("SAMPLE DATA")


def test_every_results_tab_renders(window):
    for key, _label in window.tabs._tabs.items():
        window.tabs.select(key)
        window.update()
        assert window.deck.pages[key].winfo_exists()


def test_every_detail_tab_renders_for_several_shows(window):
    for row in window.rows[:3]:
        window._select_row(row)
        for key, _label in DETAIL_TABS:
            window.detail.tabs.select(key)
            window.update()
    assert window.detail.row is not None


def test_the_detail_pane_follows_the_selected_row(window):
    target = window.rows[2]
    window.grid_view.select_key(target.key)
    window.update()
    assert window.detail.row is not None
    assert window.detail.row.key == target.key
    assert window.detail.title.cget("text") == target.event.name


def test_searching_narrows_the_table_and_the_headline_count(window):
    before = len(window.rows)
    window._on_search("salsa")
    window.update()
    assert 0 < len(window.rows) < before
    assert all("salsa" in r.search_blob() for r in window.rows)
    window._on_search("")
    window.update()
    assert len(window.rows) == before


def test_a_search_with_no_hits_empties_the_table_without_erroring(window):
    window._on_search("zzzznotathing")
    window.update()
    assert window.rows == []
    assert window.page_label.cget("text") == "No festivals to show"
    window._on_search("")
    window.update()


def test_the_event_type_dropdown_filters_by_category(window):
    window.event_type.set("crafts", notify=True)
    window.update()
    assert window.rows
    assert all(r.get("category_key") == "crafts" for r in window.rows)
    window.event_type.set(vm.ALL_TYPES, notify=True)
    window.update()


def test_every_ranking_choice_reorders_without_error(window):
    for key, _label in vm.SORT_ORDERS:
        window.rank.select(key)
        window.update()
        assert window.sort_order == key
        assert len(window.rows) == len(window.all_rows)


def test_paging_moves_through_the_result_set(window):
    window.page_size = 10
    window._refresh(reset_page=True)
    window.update()
    first_page = [r.key for r in vm.page_slice(window.rows, 1, 10)]
    window._go_to_page(2)
    window.update()
    assert window.page == 2
    assert [r.key for r in window.grid_view.rows] != first_page
    window._go_to_page(999)
    window.update()
    assert window.page == vm.page_count(len(window.rows), 10)


def test_choosing_columns_changes_what_the_table_draws(window):
    window._on_columns_change(["name", "city", "est_profit"])
    window.update()
    assert window.grid_view.columns == ["name", "city", "est_profit"]
    window._on_columns_change(list(vm.DEFAULT_COLUMNS))
    window.update()


def test_clicking_a_heading_sorts_by_that_column(window):
    event = type("Event", (), {"x": 5})()      # inside the first column
    window.grid_view._on_header_click(event)
    window.update()
    assert window.column_sort is not None
    assert window.column_sort[0] == window.grid_view.columns[0]


def test_export_writes_every_requested_format(window, tmp_path):
    out = tmp_path / "exports"
    window.export_panel.set_folder(str(out))
    for key in ("csv", "xlsx", "md", "json"):
        window.export_panel.formats[key].set(True)
    written = window.export_panel.export()
    window.update()
    assert {p.suffix for p in written} == {".csv", ".xlsx", ".md", ".json"}
    assert all(p.exists() and p.stat().st_size > 0 for p in written)


def test_exported_results_load_back_into_the_window(window, tmp_path):
    out = tmp_path / "roundtrip"
    window.export_panel.set_folder(str(out))
    for key, wanted in (("csv", False), ("xlsx", False), ("md", False),
                        ("json", True)):
        window.export_panel.formats[key].set(wanted)
    written = window.export_panel.export()
    window.update()
    expected = len(window.all_rows)
    window.clear_results()
    window.update()
    assert window.all_rows == []
    assert window.load_results_file(written[0])
    window.update()
    assert len(window.all_rows) == expected
    assert window.sample_badge.cget("text") == ""


def test_settings_survive_a_save_and_load(window, tmp_path):
    window.keyword.set("harvest")
    window.jobs.set("7")
    window.rank.select("profit")
    window.geocode.set(False)
    window.update()

    saved = window.gather_settings()
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(saved), encoding="utf-8")

    window.keyword.set("")
    window.jobs.set("2")
    window.rank.select("name")
    window.geocode.set(True)
    window.update()

    window.apply_settings(json.loads(path.read_text(encoding="utf-8")))
    window.update()
    assert window.keyword.get() == "harvest"
    assert window.jobs.value() == 7
    assert window.rank.value == "profit"
    assert window.geocode.get() is False


def test_the_rail_settings_become_a_crawl_the_pipeline_can_run(window):
    from fnscraper.gui import scrape

    window.state.set("Ohio (OH)")
    window.event_type.set("crafts")
    window.jobs.set("3")
    window.all_pages.set(False)
    window.update()

    settings = scrape.settings_for(window.crawl_options())
    assert settings.states == ["Ohio"]
    assert settings.categories == {"crafts"}
    assert settings.jobs == 3
    assert settings.max_pages_per_state == 1


def test_the_status_bar_prints_counters_including_a_reset_to_zero(window):
    window._show_counters({"requests": 4_892, "failures": 3})
    window.update()
    assert window.request_label.cget("text") == "Requests: 4,892"
    assert window.failed_label.cget("text") == "Failed: 3"
    # A new crawl has to clear the last one's totals, not keep reporting them.
    window._show_counters({})
    window.update()
    assert window.request_label.cget("text") == "Requests: 0"
    assert window.failed_label.cget("text") == "Failed: 0"


def test_a_progress_event_moves_the_counters(window):
    from fnscraper.gui import scrape

    window._on_scrape_event(scrape.PROGRESS, scrape.Progress(
        stage="crawl", done=3, total=25, message="Ohio: 412 listings so far",
        requests=137, failures=2,
    ))
    window.update()
    assert window.request_label.cget("text") == "Requests: 137"
    assert window.failed_label.cget("text") == "Failed: 2"
    assert "Crawling listings 3/25" in window.status.cget("text")


def test_stop_is_only_offered_while_a_crawl_is_running(window):
    assert window.start_button.enabled is True
    assert window.stop_button.enabled is False


def test_clearing_results_empties_every_panel(window):
    window.clear_results()
    window.update()
    assert window.all_rows == [] and window.rows == []
    assert window.grid_view.rows == []
    assert window.detail.row is None
    assert window.results_title.cget("text") == "Results (0 festivals)"


def _wait_for(window, predicate, seconds=10.0):
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        window.update()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stalled_read(display_available, tmp_path, monkeypatch):
    """A saved results file whose read blocks, like an iCloud placeholder.

    macOS evicts files in an iCloud-synced Documents folder; reading one
    blocks in read() until the download finishes.  Startup used to do that
    read on the Tk thread, so the window never appeared.
    """
    import threading

    from fnscraper import persist
    from fnscraper.gui import demo, paths, scrape

    out = tmp_path / "out"
    monkeypatch.setattr(paths, "default_output_dir", lambda: out)
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(paths, "settings_file",
                        lambda: tmp_path / "settings.json")
    saved = persist.save_results(demo.sample_results(),
                                 scrape.default_results_path(out))
    release = threading.Event()
    real_load = persist.load_results

    def slow_load(path):
        release.wait(30)
        return real_load(path)

    monkeypatch.setattr(persist, "load_results", slow_load)
    yield saved, release
    release.set()


def test_window_opens_while_saved_results_are_still_downloading(stalled_read):
    import time

    from fnscraper.gui import app as app_module

    _saved, release = stalled_read
    started = time.monotonic()
    win = app_module.ScraperWindow()
    try:
        win.update()
        assert time.monotonic() - started < 5, "window blocked on the read"
        assert win.all_rows == []
        assert "Loading saved results" in win.status.cget("text")
        release.set()
        assert _wait_for(win, lambda: len(win.all_rows) > 20)
    finally:
        win.destroy()


def test_a_slow_load_never_overwrites_newer_results(stalled_read):
    from fnscraper.gui import app as app_module

    _saved, release = stalled_read
    win = app_module.ScraperWindow()
    try:
        win.update()
        win.load_sample()
        sample_count = len(win.all_rows)
        release.set()
        _wait_for(win, lambda: win._loads.empty(), seconds=3)
        for _ in range(20):
            win.update()
        assert win.sample_data is True
        assert len(win.all_rows) == sample_count
    finally:
        win.destroy()


def test_cloud_placeholder_detection(tmp_path, monkeypatch):
    import os
    import types

    from fnscraper.gui import paths

    plain = tmp_path / "results.json"
    plain.write_text("{}")
    assert not paths.is_cloud_placeholder(plain)
    assert not paths.is_cloud_placeholder(tmp_path / "missing.json")
    monkeypatch.setattr(os, "stat", lambda _p: types.SimpleNamespace(
        st_flags=paths.SF_DATALESS))
    assert paths.is_cloud_placeholder(plain)


# ---------------------------------------------------------------------------
# responsiveness: work the window must *not* do
# ---------------------------------------------------------------------------

def test_typing_a_word_refilters_once_not_per_letter(window, monkeypatch):
    calls = []
    real = window._refresh
    monkeypatch.setattr(window, "_refresh",
                        lambda *a, **k: (calls.append(1), real(*a, **k)))
    text = ""
    for letter in "harvest":
        text += letter
        window.keyword.set(text)
        window.update()
    assert calls == []                        # still waiting for a pause
    assert _wait_for(window, lambda: window._refresh_job is None, 2.0)
    assert len(calls) == 1
    assert all(vm.Filters(keyword="harvest").matches(r) for r in window.rows)


def test_the_results_search_box_waits_for_a_pause_too(window):
    before = len(window.rows)
    window.search.set("salsa")
    window.update()
    assert len(window.rows) == before
    assert _wait_for(window, lambda: len(window.rows) < before, 2.0)


def test_hidden_tabs_are_drawn_when_opened_not_on_every_change(window, monkeypatch):
    drawn = []
    monkeypatch.setattr(window.map_panel, "set_rows",
                        lambda rows: drawn.append(len(rows)))
    window._on_search("salsa")
    window._on_search("")
    window.update()
    assert drawn == []                         # map is not on screen
    window.tabs.select("map")
    window.update()
    assert drawn == [len(window.rows)]
    window.tabs.select("map")                  # nothing changed since
    assert drawn == [len(window.rows)]


def test_a_hidden_page_is_unmapped_so_resizes_skip_it(window):
    window.tabs.select("overview")
    window.update()
    assert window.deck.pages["overview"].winfo_ismapped()
    assert not window.deck.pages["map"].winfo_ismapped()
    window.tabs.select("map")
    window.update()
    assert window.deck.pages["map"].winfo_ismapped()
    assert not window.deck.pages["overview"].winfo_ismapped()


def test_turning_a_page_does_not_redraw_the_map(window, monkeypatch):
    window.tabs.select("map")
    window.update()
    drawn = []
    monkeypatch.setattr(window.map_panel, "set_rows",
                        lambda rows: drawn.append(len(rows)))
    window._go_to_page(2)
    window.update()
    assert drawn == []


def test_the_detail_pane_builds_only_the_tab_on_screen(window):
    detail = window.detail
    window._select_row(window.rows[1])
    window.update()
    assert detail._built == {detail.tabs.active}
    other = next(key for key, _ in DETAIL_TABS if key != detail.tabs.active)
    assert detail._bodies[other].body.winfo_children() == []
    detail.tabs.select(other)
    window.update()
    assert other in detail._built
    assert detail._bodies[other].body.winfo_children() != []


def test_elision_matches_dropping_one_letter_at_a_time(window):
    """Bisection must land on what the old one-character loop produced."""
    grid = window.grid_view
    font, _bold = grid._fonts()

    def one_at_a_time(text, width):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text.rstrip() + "…"

    for text in ("The Extremely Long Annual Harvest Festival Of Many Words",
                 "$17,098", "Short", "https://festivalnet.com/a/very/long/url"):
        for width in (5, 40, 90, 150, 400):
            assert grid._elide(text, font, width) == one_at_a_time(text, width)


def test_closing_with_a_refresh_pending_raises_nothing(display_available,
                                                       tmp_path, monkeypatch):
    from fnscraper.gui import app as app_module, paths

    monkeypatch.setattr(paths, "default_output_dir", lambda: tmp_path / "out")
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(paths, "settings_file", lambda: tmp_path / "s.json")
    win = app_module.ScraperWindow(sample=True)
    win.update()
    win.keyword.set("fair")
    assert win._refresh_job is not None
    win.destroy()                              # must cancel, not fire later

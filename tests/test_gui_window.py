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

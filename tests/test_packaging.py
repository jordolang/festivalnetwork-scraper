"""The build driver's decisions, without running a build.

`packaging/build.py` is a script rather than a package module, so it is
loaded by path.  Nothing here shells out: the point is to pin the naming
that CI greps for and the retry that a busy disk-image device needs.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "fn_build", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# artifact naming — CI greps for these exact suffixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host,arch,suffix,expected", [
    ("windows", "x64", ".exe", "FestivalNet-Scraper-{v}-windows-x64.exe"),
    ("windows", "arm64", ".exe", "FestivalNet-Scraper-{v}-windows-arm64.exe"),
    ("macos", "arm64", ".dmg", "FestivalNet-Scraper-{v}-macos-arm64.dmg"),
    ("macos", "universal2", ".dmg",
     "FestivalNet-Scraper-{v}-macos-universal2.dmg"),
])
def test_artifact_names_match_what_the_release_job_looks_for(
        build, monkeypatch, host, arch, suffix, expected):
    monkeypatch.setattr(build, "host_os", lambda: host)
    assert build.artifact_name(arch, suffix).name == \
        expected.format(v=build.version())


def test_version_comes_from_the_package(build):
    from fnscraper import __version__
    assert build.version() == __version__


def test_pyinstaller_arch_spelling(build):
    """PyInstaller wants x86_64; this script says x64 everywhere else."""
    assert build.PYINSTALLER_ARCH["x64"] == "x86_64"
    assert build.PYINSTALLER_ARCH["arm64"] == "arm64"
    assert build.PYINSTALLER_ARCH["universal2"] == "universal2"


def test_every_host_arch_alias_maps_somewhere_known(build):
    for alias in ("amd64", "x86_64", "x64", "arm64", "aarch64"):
        assert build.ARCH_ALIASES[alias] in build.PYINSTALLER_ARCH


# ---------------------------------------------------------------------------
# hdiutil retry — "Resource busy" is a device that clears, not a bad build
# ---------------------------------------------------------------------------

def _stage_dmg(build, monkeypatch, tmp_path, results):
    """Point make_dmg at a temp tree and script what `run` does."""
    monkeypatch.setattr(build, "host_os", lambda: "macos")
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build, "BUILD", tmp_path / "build")
    (tmp_path / "dist").mkdir()
    app = tmp_path / "FestivalNet Scraper.app"
    app.mkdir()
    monkeypatch.setattr(build.time, "sleep", lambda _s: None)

    calls = []

    def fake_run(command, **kw):
        calls.append(command)
        if command[0] == "cp":
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return
        outcome = results.pop(0)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(build, "run", fake_run)
    return app, calls


def test_dmg_creation_retries_a_busy_device(build, monkeypatch, tmp_path):
    busy = subprocess.CalledProcessError(1, "hdiutil")
    app, calls = _stage_dmg(build, monkeypatch, tmp_path, [busy, busy, None])

    dmg = build.make_dmg(app, "universal2")

    assert dmg.name.endswith("-macos-universal2.dmg")
    hdiutil_calls = [c for c in calls if c[0] == "hdiutil"]
    assert len(hdiutil_calls) == 3, "should have retried twice then succeeded"


def test_dmg_creation_gives_up_rather_than_looping(build, monkeypatch, tmp_path):
    busy = subprocess.CalledProcessError(1, "hdiutil")
    app, calls = _stage_dmg(build, monkeypatch, tmp_path, [busy] * 4)

    with pytest.raises(subprocess.CalledProcessError):
        build.make_dmg(app, "arm64", attempts=4)

    assert len([c for c in calls if c[0] == "hdiutil"]) == 4


def test_a_dmg_that_builds_first_time_is_not_retried(build, monkeypatch, tmp_path):
    app, calls = _stage_dmg(build, monkeypatch, tmp_path, [None])

    build.make_dmg(app, "arm64")

    assert len([c for c in calls if c[0] == "hdiutil"]) == 1


def test_the_dmg_carries_an_applications_symlink(build, monkeypatch, tmp_path):
    """Without it there is nowhere to drag the app to."""
    app, _calls = _stage_dmg(build, monkeypatch, tmp_path, [None])

    build.make_dmg(app, "arm64")

    link = tmp_path / "build" / "dmg" / "Applications"
    assert link.is_symlink()
    assert str(link.readlink()) == "/Applications"

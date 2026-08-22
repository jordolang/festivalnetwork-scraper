"""Build the desktop app for the machine (or architecture) you point it at.

    python packaging/build.py                  # this machine's architecture
    python packaging/build.py --target arm64   # macOS cross-build

Four artifacts, one per platform/architecture pair, each in the form that
platform's users expect to download:

    FestivalNet-Scraper-<version>-windows-x64.exe     one self-contained .exe
    FestivalNet-Scraper-<version>-windows-arm64.exe
    FestivalNet-Scraper-<version>-macos-x64.dmg       a mountable disk image
    FestivalNet-Scraper-<version>-macos-arm64.dmg

Windows cannot cross-build: an ARM64 .exe has to come off an ARM64
runner, because the frozen app embeds that machine's CPython and its
extension modules.  macOS can, as long as every wheel in the environment
carries the slice you are asking for.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "FestivalNet Scraper"
SPEC = ROOT / "packaging" / "festivalnet.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

# What this script calls an architecture, from whatever the machine calls it.
ARCH_ALIASES = {
    "amd64": "x64", "x86_64": "x64", "x64": "x64",
    "arm64": "arm64", "aarch64": "arm64",
    "universal2": "universal2",
}
# ...and what PyInstaller calls it, which is not the same spelling.
PYINSTALLER_ARCH = {
    "x64": "x86_64", "arm64": "arm64", "universal2": "universal2",
}


def host_arch() -> str:
    return ARCH_ALIASES.get(platform.machine().lower(), platform.machine().lower())


def host_os() -> str:
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return sys.platform


def version() -> str:
    text = (ROOT / "fnscraper" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def run(command: list[str], **kw) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kw)


def check_prerequisites() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is missing.  pip install -r requirements-build.txt")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit(
            "This Python has no Tk support, so it cannot build a windowed "
            "app.\n  macOS/Windows: use the python.org installer.\n"
            "  Linux: install the python3-tk package."
        )
    icons = ROOT / "assets" / "icons"
    if not (icons / "festivalnet.ico").is_file():
        print("Icons missing; generating them.")
        run([sys.executable, str(ROOT / "tools" / "make_app_icon.py")])


def raw_output() -> Path:
    """What PyInstaller leaves in dist/, before it is named for release."""
    if host_os() == "macos":
        return DIST / f"{APP_NAME}.app"
    if host_os() == "windows":
        return DIST / f"{APP_NAME}.exe"
    return DIST / APP_NAME


def freeze(target_arch: str | None) -> Path:
    env = dict(os.environ, FN_VERSION=version())
    if target_arch:
        env["FN_TARGET_ARCH"] = PYINSTALLER_ARCH[target_arch]
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(BUILD), str(SPEC)],
        env=env, cwd=str(ROOT))
    built = raw_output()
    if not built.exists():
        sys.exit(f"PyInstaller did not produce {built}")
    return built


def artifact_name(arch: str, suffix: str) -> Path:
    return DIST / f"FestivalNet-Scraper-{version()}-{host_os()}-{arch}{suffix}"


def package(built: Path, arch: str) -> Path:
    """Turn the raw build into the file people download."""
    if host_os() == "macos":
        return make_dmg(built, arch)
    if host_os() == "windows":
        # The one-file build already *is* the deliverable; it only needs
        # the name that says which machine it belongs to.
        target = artifact_name(arch, ".exe")
        target.unlink(missing_ok=True)
        shutil.copy2(built, target)
        return target
    # Linux is not a release target; a tarball keeps local builds tidy.
    target = artifact_name(arch, ".tar.gz")
    target.unlink(missing_ok=True)
    shutil.make_archive(str(target).removesuffix(".tar.gz"), "gztar",
                        root_dir=str(built.parent), base_dir=built.name)
    return target


# hdiutil attaches the image it is building, and macOS's diskimages helper
# can still be holding the device from a previous operation when it does.
# The result is `hdiutil: create failed - Resource busy` on a build that is
# otherwise perfect.  It clears in seconds.
DMG_ATTEMPTS = 4
DMG_RETRY_SECONDS = 5


def make_dmg(built: Path, arch: str, attempts: int = DMG_ATTEMPTS) -> Path:
    """A mountable image with the app and a drag-here Applications link."""
    dmg = artifact_name(arch, ".dmg")
    dmg.unlink(missing_ok=True)
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    # cp -R, not shutil.copytree: a .app is full of symlinked frameworks
    # and executable bits that a naive copy flattens, and macOS then
    # refuses to open the result.
    run(["cp", "-R", str(built), str(staging / built.name)])
    os.symlink("/Applications", staging / "Applications")

    command = ["hdiutil", "create", "-volname", APP_NAME,
               "-srcfolder", str(staging), "-ov", "-format", "UDZO", str(dmg)]
    for attempt in range(1, attempts + 1):
        try:
            run(command)
            return dmg
        except subprocess.CalledProcessError:
            if attempt == attempts:
                # Out of patience: this is no longer a busy device.
                raise
            wait = DMG_RETRY_SECONDS * attempt
            print(f"hdiutil failed (attempt {attempt}/{attempts}); "
                  f"retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")          # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=sorted(set(ARCH_ALIASES.values())),
                        help="architecture to build for (macOS only; "
                             "defaults to this machine's)")
    parser.add_argument("--no-package", action="store_true",
                        help="leave PyInstaller's raw output, skip the "
                             ".dmg/.exe naming step")
    args = parser.parse_args(argv)

    arch = args.target or host_arch()
    if args.target and host_os() != "macos" and args.target != host_arch():
        sys.exit(
            f"Cannot build a {args.target} app on {host_os()}/{host_arch()}. "
            "Windows ARM64 builds need an ARM64 Windows machine or runner."
        )

    check_prerequisites()
    print(f"Building {APP_NAME} {version()} for {host_os()}-{arch}")
    built = freeze(args.target if host_os() == "macos" else None)
    print(f"App: {built}")

    if not args.no_package:
        print(f"Artifact: {package(built, arch)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

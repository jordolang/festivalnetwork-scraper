"""Build the desktop app for the machine (or architecture) you point it at.

    python packaging/build.py                  # this machine's architecture
    python packaging/build.py --target arm64   # macOS cross-build
    python packaging/build.py --dmg            # also roll a .dmg

Four artifacts are supported, one per platform/architecture pair:

    FestivalNet-Scraper-<version>-windows-x64.zip
    FestivalNet-Scraper-<version>-windows-arm64.zip
    FestivalNet-Scraper-<version>-macos-x64.zip
    FestivalNet-Scraper-<version>-macos-arm64.zip

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


def freeze(target_arch: str | None) -> Path:
    env = dict(os.environ, FN_VERSION=version())
    if target_arch:
        env["FN_TARGET_ARCH"] = PYINSTALLER_ARCH[target_arch]
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(BUILD), str(SPEC)],
        env=env, cwd=str(ROOT))
    built = DIST / (f"{APP_NAME}.app" if host_os() == "macos" else APP_NAME)
    if not built.exists():
        sys.exit(f"PyInstaller did not produce {built}")
    return built


def package(built: Path, arch: str) -> Path:
    stem = f"FestivalNet-Scraper-{version()}-{host_os()}-{arch}"
    archive = DIST / f"{stem}.zip"
    archive.unlink(missing_ok=True)
    if host_os() == "macos":
        # ditto, not zip: a .app is full of symlinked frameworks and
        # executable bits that a naive archiver flattens, and macOS then
        # refuses to open the copy.
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             str(built), str(archive)])
    else:
        shutil.make_archive(str(archive.with_suffix("")), "zip",
                            root_dir=str(built.parent), base_dir=built.name)
    return archive


def make_dmg(built: Path, arch: str) -> Path | None:
    if host_os() != "macos":
        print("Skipping .dmg: only macOS can make one.")
        return None
    dmg = DIST / f"FestivalNet-Scraper-{version()}-macos-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run(["cp", "-R", str(built), str(staging / built.name)])
    os.symlink("/Applications", staging / "Applications")
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging),
         "-ov", "-format", "UDZO", str(dmg)])
    return dmg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=sorted(set(ARCH_ALIASES.values())),
                        help="architecture to build for (macOS only; "
                             "defaults to this machine's)")
    parser.add_argument("--dmg", action="store_true",
                        help="also build a .dmg (macOS only)")
    parser.add_argument("--no-archive", action="store_true",
                        help="leave the app folder, skip the .zip")
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

    if not args.no_archive:
        print(f"Archive: {package(built, arch)}")
    if args.dmg:
        dmg = make_dmg(built, arch)
        if dmg:
            print(f"Disk image: {dmg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

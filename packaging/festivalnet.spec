# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the FestivalNet Scraper desktop app.

One spec serves all four targets — Windows x64, Windows ARM64, macOS
Intel and macOS Apple Silicon — because the architecture comes from the
interpreter running the build, not from the recipe.  Build it with
``python packaging/build.py``, which sets the environment this reads.
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "FestivalNet Scraper"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"

# Set by packaging/build.py; only macOS can cross-target an architecture.
TARGET_ARCH = os.environ.get("FN_TARGET_ARCH") or None
VERSION = os.environ.get("FN_VERSION", "1.0.0")

icon = str(ROOT / "assets" / "icons" /
           ("festivalnet.icns" if IS_MAC else "festivalnet.ico"))

analysis = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # The window loads its taskbar icon from here at runtime.
    datas=[(str(ROOT / "assets" / "icons"), "assets/icons")],
    hiddenimports=[
        "fnscraper.gui.app",
        "fnscraper.pipeline",
        "fnscraper.persist",
        "fnscraper.export",
        "openpyxl",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here imports a scientific stack; excluding them keeps the
    # bundle around 20 MB instead of 200.
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy", "PIL",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "IPython", "pytest", "setuptools", "pip",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME if not IS_WINDOWS else "FestivalNet Scraper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # a GUI app must not flash a console window
    disable_windowed_traceback=False,
    target_arch=TARGET_ARCH,
    codesign_identity=os.environ.get("FN_CODESIGN_IDENTITY") or None,
    entitlements_file=(str(ROOT / "packaging" / "entitlements.plist")
                       if IS_MAC else None),
    icon=icon,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if IS_MAC:
    app = BUNDLE(
        collect,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.jordolang.fnscraper",
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.business",
            "NSHumanReadableCopyright":
                "Open source — see the project's LICENSE.",
        },
    )

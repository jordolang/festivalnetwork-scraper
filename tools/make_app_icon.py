"""Generate the desktop app's icon in the three formats a build needs.

    python tools/make_app_icon.py

Writes ``assets/icons/festivalnet.ico`` (Windows executables and shortcuts),
``festivalnet.icns`` (the macOS .app bundle), and a few PNGs — one of which
Tk loads at runtime for the window/taskbar icon.

Like ``tools/make_icons.py``, which this borrows its drawing helpers from,
the image is a plain per-pixel function so the build needs no imaging
library: PNG is written with the standard library's zlib, and .icns is
just a container of PNGs.
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_icons import _bar, _edge, _over, _rect, _ring, _rounded, write_ico  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
STEM = "festivalnet"

# Matches the window's accent palette (fnscraper/gui/theme.py).
TILE_DARK = (26, 30, 46)
TILE_LIGHT = (37, 54, 92)
ACCENT = (47, 128, 237)
GREEN = (94, 212, 154)
PAPER = (238, 243, 255)


def app_icon(x: float, y: float) -> tuple:
    """A magnifier over a rising bar chart: search, then score."""
    tile = _rounded(x, y, 0.22)
    px = _over((0, 0, 0, 0.0), TILE_DARK, tile)
    # Vertical lift, so the tile reads as a surface and not a flat block.
    px = _over(px, TILE_LIGHT, tile * _edge(0.52 - y, 0.75))

    # Three bars, tallest last — the score ranking.
    bars = ((0.26, 0.62), (0.44, 0.50), (0.62, 0.36))
    for x0, top in bars:
        px = _over(px, GREEN, min(_rect(x, y, x0, top, x0 + 0.12, 0.78), tile))

    # Magnifier: ring, then handle, over the bars.
    # A faint wash inside the lens, not a fill: the bars have to stay
    # visible through the glass or the mark reads as an empty magnifier.
    lens = _edge(0.215 - math.hypot(x - 0.45, y - 0.45))
    px = _over(px, PAPER, lens * 0.10)
    px = _over(px, ACCENT, _bar(x, y, 0.60, 0.60, 0.80, 0.80, 0.115))
    px = _over(px, PAPER, _bar(x, y, 0.60, 0.60, 0.80, 0.80, 0.055))
    px = _over(px, PAPER, _ring(x, y, 0.45, 0.45, 0.235, 0.085))
    return px


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------

def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(
        ">I", zlib.crc32(body) & 0xFFFFFFFF)


def png_bytes(draw, size: int) -> bytes:
    """An 8-bit RGBA PNG of ``draw`` rendered at ``size`` x ``size``."""
    rows = bytearray()
    for py in range(size):
        rows.append(0)                       # filter type 0 (None)
        for px_i in range(size):
            r, g, b, a = draw((px_i + 0.5) / size, (py + 0.5) / size)
            rows += bytes((round(r), round(g), round(b), round(a * 255)))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + _chunk(b"IEND", b""))


def write_png(draw, path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(draw, size))
    return path


# ---------------------------------------------------------------------------
# ICNS — a length-prefixed container of PNGs, one per OSType
# ---------------------------------------------------------------------------

# (OSType, pixel size).  PNG-backed types, supported since OS X 10.7.
ICNS_TYPES = (
    (b"ic11", 32),      # 16pt @2x
    (b"ic12", 64),      # 32pt @2x
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
)


def write_icns(draw, path: Path) -> Path:
    entries = b""
    for ostype, size in ICNS_TYPES:
        blob = png_bytes(draw, size)
        entries += ostype + struct.pack(">I", len(blob) + 8) + blob
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"icns" + struct.pack(">I", len(entries) + 8) + entries)
    return path


def main() -> None:
    written = [
        write_ico(app_icon, OUT_DIR / f"{STEM}.ico", sizes=(16, 32, 48, 256)),
        write_icns(app_icon, OUT_DIR / f"{STEM}.icns"),
        write_png(app_icon, OUT_DIR / f"{STEM}-256.png", 256),
        write_png(app_icon, OUT_DIR / f"{STEM}-64.png", 64),
    ]
    for path in written:
        print(f"{path}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

"""Generate the Windows shortcut icons in windows/icons/.

Hand-rolled ICO writer so the build has no image-library dependency: the
icons are drawn as plain per-pixel functions and written as 32-bit BGRA
bitmaps, which is what Explorer wants.  Run it only when an icon changes:

    python tools/make_icons.py
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

SIZES = (16, 32, 48, 256)
OUT_DIR = Path(__file__).resolve().parent.parent / "windows" / "icons"


# ---------------------------------------------------------------------------
# Drawing helpers.  Coordinates are 0..1 so one drawing serves every size.
# ---------------------------------------------------------------------------

def _rounded(x: float, y: float, radius: float = 0.22) -> float:
    """Coverage of a rounded square filling the tile, 0..1 (antialiased)."""
    dx = max(abs(x - 0.5) - (0.5 - radius), 0.0)
    dy = max(abs(y - 0.5) - (0.5 - radius), 0.0)
    dist = math.hypot(dx, dy)
    return _edge(radius - dist)


def _edge(signed: float, softness: float = 0.012) -> float:
    """Antialiased step: 1 well inside, 0 well outside."""
    return min(max(signed / softness + 0.5, 0.0), 1.0)


def _ring(x: float, y: float, cx: float, cy: float, r: float,
          thickness: float) -> float:
    d = abs(math.hypot(x - cx, y - cy) - r)
    return _edge(thickness / 2 - d)


def _bar(x: float, y: float, x0: float, y0: float, x1: float, y1: float,
         thickness: float) -> float:
    """Coverage of a thick line segment."""
    vx, vy = x1 - x0, y1 - y0
    length_sq = vx * vx + vy * vy or 1e-9
    t = min(max(((x - x0) * vx + (y - y0) * vy) / length_sq, 0.0), 1.0)
    d = math.hypot(x - (x0 + t * vx), y - (y0 + t * vy))
    return _edge(thickness / 2 - d)


def _rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float) -> float:
    inside = min(x - x0, x1 - x, y - y0, y1 - y)
    return _edge(inside)


def _over(base: tuple, layer: tuple, alpha: float) -> tuple:
    """Composite an opaque colour over the accumulated pixel."""
    if alpha <= 0:
        return base
    br, bg, bb, ba = base
    lr, lg, lb = layer
    out_a = alpha + ba * (1 - alpha)
    if out_a <= 0:
        return (0, 0, 0, 0.0)
    mix = lambda l, b: (l * alpha + b * ba * (1 - alpha)) / out_a
    return (mix(lr, br), mix(lg, bg), mix(lb, bb), out_a)


# ---------------------------------------------------------------------------
# The three icons
# ---------------------------------------------------------------------------

def find_shows(x: float, y: float) -> tuple:
    """Warm tile with a magnifying glass over a dollar sign."""
    px = _over((0, 0, 0, 0.0), (214, 92, 32), _rounded(x, y))
    px = _over(px, (255, 176, 59), _rounded(x, y) * _edge(0.46 - y, 0.25))
    handle = _bar(x, y, 0.60, 0.62, 0.79, 0.81, 0.115)
    px = _over(px, (255, 255, 255), handle)
    px = _over(px, (255, 255, 255), _ring(x, y, 0.44, 0.44, 0.235, 0.10))
    lens = _edge(0.185 - math.hypot(x - 0.44, y - 0.44))
    px = _over(px, (255, 246, 232), lens)
    stem = _bar(x, y, 0.44, 0.30, 0.44, 0.58, 0.045)
    top = _bar(x, y, 0.36, 0.375, 0.52, 0.375, 0.052)
    mid = _bar(x, y, 0.36, 0.505, 0.52, 0.505, 0.052)
    curve = max(_bar(x, y, 0.36, 0.375, 0.36, 0.44, 0.05),
                _bar(x, y, 0.52, 0.44, 0.52, 0.505, 0.05),
                _bar(x, y, 0.36, 0.44, 0.52, 0.44, 0.05))
    glyph = min(max(stem, top, mid, curve), lens)
    return _over(px, (198, 62, 22), glyph)


def settings(x: float, y: float) -> tuple:
    """Slate tile with a gear."""
    px = _over((0, 0, 0, 0.0), (55, 65, 81), _rounded(x, y))
    px = _over(px, (94, 108, 128), _rounded(x, y) * _edge(0.46 - y, 0.25))
    teeth = 0.0
    for i in range(8):
        angle = i * math.pi / 4
        cx, cy = 0.5 + 0.29 * math.cos(angle), 0.5 + 0.29 * math.sin(angle)
        teeth = max(teeth, _edge(0.105 - math.hypot(x - cx, y - cy)))
    body = _edge(0.265 - math.hypot(x - 0.5, y - 0.5))
    hole = _edge(math.hypot(x - 0.5, y - 0.5) - 0.115)
    return _over(px, (255, 255, 255), min(max(teeth, body), hole))


def reports(x: float, y: float) -> tuple:
    """Green tile with a page of results."""
    px = _over((0, 0, 0, 0.0), (21, 128, 84), _rounded(x, y))
    px = _over(px, (52, 176, 116), _rounded(x, y) * _edge(0.46 - y, 0.25))
    page = _rect(x, y, 0.27, 0.20, 0.73, 0.80)
    px = _over(px, (255, 255, 255), page)
    lines = 0.0
    for i, width in enumerate((0.38, 0.30, 0.34, 0.24)):
        top = 0.31 + i * 0.12
        lines = max(lines, _rect(x, y, 0.35, top, 0.35 + width, top + 0.055))
    return _over(px, (21, 128, 84), min(lines, page))


# ---------------------------------------------------------------------------
# ICO writing
# ---------------------------------------------------------------------------

def render(draw, size: int) -> bytes:
    """One BMP-in-ICO image: BITMAPINFOHEADER + BGRA rows + AND mask."""
    rows: list[bytes] = []
    for py in range(size - 1, -1, -1):          # DIB rows run bottom-up
        row = bytearray()
        for px_i in range(size):
            r, g, b, a = draw((px_i + 0.5) / size, (py + 0.5) / size)
            row += bytes((round(b), round(g), round(r), round(a * 255)))
        rows.append(bytes(row))
    xor = b"".join(rows)
    mask_row = (size + 31) // 32 * 4            # 1bpp, padded to 4 bytes
    and_mask = b"\x00" * (mask_row * size)
    header = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
        len(xor) + len(and_mask), 0, 0, 0, 0,
    )
    return header + xor + and_mask


def write_ico(draw, path: Path, sizes=SIZES) -> Path:
    images = [(size, render(draw, size)) for size in sizes]
    offset = 6 + 16 * len(images)
    directory, blobs = b"", b""
    for size, blob in images:
        directory += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset
        )
        blobs += blob
        offset += len(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + directory + blobs)
    return path


def main() -> None:
    for name, draw in (("find-shows", find_shows), ("settings", settings),
                       ("reports", reports)):
        # 256px at 32bpp is 256 KB per icon; the launchers only ever show
        # small sizes, so stop at 48 and keep the repo light.
        path = write_ico(draw, OUT_DIR / f"{name}.ico", sizes=(16, 32, 48))
        print(f"{path}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

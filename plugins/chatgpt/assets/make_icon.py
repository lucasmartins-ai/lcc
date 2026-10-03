"""Generate the plugin composer icon: a lightning bolt cut from a rounded tile.

Stdlib only (zlib + struct), so no image library enters the project's dependencies.
Run: ``python3 plugins/chatgpt/assets/make_icon.py`` — writes ``icon.png`` beside it.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 512
BG = (10, 15, 28)  # deep navy, matches the ChatGPT composer surface
BOLT = (45, 212, 191)  # teal: the LookADev mark colour
RADIUS = 96


def _rounded(x: int, y: int) -> bool:
    """Inside a rounded square centred on the canvas."""
    cx = min(max(x, RADIUS), SIZE - 1 - RADIUS)
    cy = min(max(y, RADIUS), SIZE - 1 - RADIUS)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= RADIUS * RADIUS


def _bolt(x: int, y: int) -> bool:
    """A lightning bolt: two offset parallelograms meeting at a waist."""
    # Normalise to the glyph's own box, then test the classic zig-zag polygon.
    u = (x - SIZE * 0.34) / (SIZE * 0.32)
    v = (y - SIZE * 0.12) / (SIZE * 0.76)
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return False
    # Slanted right edge on the upper half, left edge on the lower half.
    slant = 0.34 * (1.0 - v)
    left = 0.62 * v if v < 0.5 else 0.62 * v - 0.24
    right = left + 0.40 - slant * 0.5
    waist = 0.30 if 0.42 < v < 0.58 else 0.0
    return (left + waist) <= u <= right


def build() -> bytes:
    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)  # PNG filter type 0
        for x in range(SIZE):
            if not _rounded(x, y):
                raw += bytes((0, 0, 0, 0))  # transparent outside the tile
            elif _bolt(x, y):
                raw += bytes(BOLT) + b"\xff"
            else:
                raw += bytes(BG) + b"\xff"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    target = Path(__file__).with_name("icon.png")
    target.write_bytes(build())
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

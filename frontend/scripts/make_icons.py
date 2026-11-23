"""Draw the app icon (blue gradient with three rising bars) as PNG files.

Standard library only: shapes are rasterized by sampling each pixel 4x4 times
for smooth edges, and the PNG is written with zlib. Run from frontend/:

    python3 scripts/make_icons.py
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public"
TOP = (74, 163, 255)       # #4aa3ff
BOTTOM = (0, 122, 255)     # #007aff  (Apple blue)

# Bars in a 512-unit square, kept inside the central 60% so Android's
# circular/squircle masks never clip them ("maskable").
BARS = [(140, 290, 72, 100), (220, 290 - 70, 72, 170), (300, 290 - 150, 72, 250)]  # x, top, width, height
BASE = 390
RADIUS = 18


def inside_bar(x: float, y: float) -> bool:
    for bx, _, w, h in BARS:
        top = BASE - h
        if bx <= x <= bx + w and top <= y <= BASE:
            # Round the top corners.
            for cx in (bx + RADIUS, bx + w - RADIUS):
                if y < top + RADIUS and (x < bx + RADIUS or x > bx + w - RADIUS):
                    dx, dy = x - cx, y - (top + RADIUS)
                    if abs(x - cx) <= RADIUS and dx * dx + dy * dy > RADIUS * RADIUS:
                        return False
            return True
    return False


def render(size: int) -> bytes:
    scale = 512 / size
    samples = [(i + 0.5) / 4 for i in range(4)]
    rows = []
    for py in range(size):
        t = py / max(size - 1, 1)
        bg = [round(TOP[c] + (BOTTOM[c] - TOP[c]) * t) for c in range(3)]
        row = bytearray()
        for px in range(size):
            hits = sum(
                inside_bar((px + sx) * scale, (py + sy) * scale) for sx in samples for sy in samples
            )
            a = hits / 16
            row += bytes(round(bg[c] * (1 - a) + 255 * a) for c in range(3)) + b"\xff"
        rows.append(b"\x00" + bytes(row))
    return png(size, size, b"".join(rows))


def png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180), ("favicon-32.png", 32)]:
        (OUT / name).write_bytes(render(size))
        print("wrote", OUT / name)

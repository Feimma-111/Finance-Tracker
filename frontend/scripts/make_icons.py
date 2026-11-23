"""Draw the app icon (a white dollar sign on an Apple-blue gradient) as PNGs.

Standard library only. The "$" is two arcs forming an S plus short bars above
and below, all drawn as thick strokes with rounded ends: a pixel is "ink" if it
lies within half the stroke width of one of those shapes. Each pixel is sampled
4x4 times for smooth edges, and the PNG is written with zlib. Run from frontend/:

    python3 scripts/make_icons.py
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public"
TOP = (74, 163, 255)       # #4aa3ff
BOTTOM = (0, 122, 255)     # #007aff  (Apple blue)

# Geometry in a 512-unit square. Everything stays inside the central circle
# that Android keeps when it masks icons into circles or squircles.
CX = 256
R = 62                     # radius of each half of the S
UPPER = (CX, 196)          # centers are 2R apart so the arcs meet in the middle
LOWER = (CX, 196 + 2 * R)
HALF_STROKE = 23           # stroke width 46
# Arc sweeps (degrees, screen coordinates: 0 = right, 90 = down).
UPPER_ARC = (-270.0, -28.0)   # from the middle (bottom of the top loop), around the left, over the top, ending right
LOWER_ARC = (-90.0, 152.0)    # from the middle (top of the bottom loop), around the right, under, ending left
BAR_TOP = (CX, 92, CX, 132)                 # stub above the S
BAR_BOTTOM = (CX, 380 + 0, CX, 420)          # stub below the S
BAR_HALF = 21


def arc_distance(x, y, center, sweep):
    cx, cy = center
    a0, a1 = (math.radians(a) for a in sweep)
    angle = math.atan2(y - cy, x - cx)
    # Shift the angle into [a0, a0 + 2pi) to test whether it's inside the sweep.
    shifted = a0 + (angle - a0) % (2 * math.pi)
    if shifted <= a1:
        return abs(math.hypot(x - cx, y - cy) - R)
    ends = [(cx + R * math.cos(a), cy + R * math.sin(a)) for a in (a0, a1)]
    return min(math.hypot(x - ex, y - ey) for ex, ey in ends)  # rounded caps


def segment_distance(x, y, seg):
    x1, y1, x2, y2 = seg
    t = max(0.0, min(1.0, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / ((x2 - x1) ** 2 + (y2 - y1) ** 2)))
    return math.hypot(x - (x1 + t * (x2 - x1)), y - (y1 + t * (y2 - y1)))


def is_ink(x, y):
    if not (150 <= x <= 362 and 60 <= y <= 452):  # quick reject outside the glyph's box
        return False
    return (
        arc_distance(x, y, UPPER, UPPER_ARC) <= HALF_STROKE
        or arc_distance(x, y, LOWER, LOWER_ARC) <= HALF_STROKE
        or segment_distance(x, y, BAR_TOP) <= BAR_HALF
        or segment_distance(x, y, BAR_BOTTOM) <= BAR_HALF
    )


def render(size):
    scale = 512 / size
    offsets = [(i + 0.5) / 4 for i in range(4)]
    rows = []
    for py in range(size):
        t = py / max(size - 1, 1)
        bg = [round(TOP[c] + (BOTTOM[c] - TOP[c]) * t) for c in range(3)]
        row = bytearray()
        for px in range(size):
            hits = sum(is_ink((px + sx) * scale, (py + sy) * scale) for sx in offsets for sy in offsets)
            a = hits / 16
            row += bytes(round(bg[c] * (1 - a) + 255 * a) for c in range(3)) + b"\xff"
        rows.append(b"\x00" + bytes(row))
    return png(size, size, b"".join(rows))


def png(width, height, raw):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180), ("favicon-32.png", 32)]:
        (OUT / name).write_bytes(render(size))
        print("wrote", OUT / name)

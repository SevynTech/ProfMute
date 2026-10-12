"""Draw profmute.ico: a muted-speaker mark on a blue tile. Only needed if you want to change the icon.

Usage (from the project folder):  uv run python launcher\\make_icon.py
"""
import struct
from pathlib import Path

import numpy as np

SIZES = (256, 128, 64, 48, 32, 24, 16)
BLUE, WHITE = (59, 130, 246), (255, 255, 255)


def draw(n):
    """The icon as an n x n RGBA array, drawn 4x too large and averaged down for smooth edges."""
    big = n * 4
    y, x = (np.mgrid[0:big, 0:big] + 0.5) / big

    def near_segment(x0, y0, x1, y1, width):
        dx, dy = x1 - x0, y1 - y0
        t = np.clip(((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy), 0, 1)
        return np.hypot(x - (x0 + t * dx), y - (y0 + t * dy)) <= width

    # rounded tile
    r, inset = 0.2, 0.04
    cx, cy = np.clip(x, inset + r, 1 - inset - r), np.clip(y, inset + r, 1 - inset - r)
    tile = np.hypot(x - cx, y - cy) <= r
    # speaker: a box and a cone
    box = (x >= 0.17) & (x <= 0.31) & (np.abs(y - 0.5) <= 0.10)
    cone = (x >= 0.30) & (x <= 0.48) & (np.abs(y - 0.5) <= 0.10 + (x - 0.30) / 0.18 * 0.17)
    # the X that says "muted"
    cross = near_segment(0.60, 0.39, 0.82, 0.61, 0.038) | near_segment(0.60, 0.61, 0.82, 0.39, 0.038)

    rgba = np.zeros((big, big, 4))
    rgba[tile] = (*BLUE, 255)
    rgba[tile & (box | cone | cross)] = (*WHITE, 255)
    rgba[..., :3] *= rgba[..., 3:] / 255                      # average colors weighted by coverage
    small = rgba.reshape(n, 4, n, 4, 4).mean(axis=(1, 3))
    alpha = small[..., 3:]
    small[..., :3] = np.divide(small[..., :3] * 255, alpha, out=np.zeros_like(small[..., :3]), where=alpha > 0)
    return np.clip(small.round(), 0, 255).astype(np.uint8)


def dib(rgba):
    """One icon image in the classic (uncompressed) format every Windows tool accepts."""
    n = rgba.shape[0]
    pixels = rgba[::-1, :, [2, 1, 0, 3]].tobytes()             # bottom-up, BGRA
    mask = bytes(((n + 31) // 32) * 4 * n)                     # unused: transparency comes from alpha
    return struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0) + pixels + mask


def main():
    images = [dib(draw(n)) for n in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for n, data in zip(SIZES, images):
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path = Path(__file__).resolve().parent.parent / "profmute.ico"
    path.write_bytes(out + b"".join(images))
    print("wrote", path)


if __name__ == "__main__":
    main()

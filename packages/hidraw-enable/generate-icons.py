#!/usr/bin/env python3
"""Generate the package's simple, dependency-free placeholder icons."""

import struct
import zlib
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent / "spk"


def rectangle(pixels, size, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(size, y1)):
        start = y * size
        for x in range(max(0, x0), min(size, x1)):
            pixels[start + x] = color


def draw_icon(size):
    pixels = [(20, 39, 63)] * (size * size)
    scale = size / 256

    def point(value):
        return round(value * scale)

    center = point(128)
    radius = point(99)
    for y in range(size):
        for x in range(size):
            if (x - center) ** 2 + (y - center) ** 2 <= radius**2:
                pixels[y * size + x] = (32, 174, 190)

    rectangle(pixels, size, point(45), point(75), point(211), point(182), (244, 250, 252))
    rectangle(pixels, size, point(57), point(87), point(199), point(169), (20, 39, 63))

    for row, keys in enumerate((9, 8, 7)):
        y0 = point(96 + row * 20)
        y1 = point(108 + row * 20)
        gap = point(4)
        left = point(65 + row * 5)
        available = point(126 - row * 10)
        key_width = (available - gap * (keys - 1)) // keys
        for key in range(keys):
            x0 = left + key * (key_width + gap)
            rectangle(pixels, size, x0, y0, x0 + key_width, y1, (244, 250, 252))

    rectangle(pixels, size, point(96), point(157), point(160), point(165), (255, 187, 72))
    rectangle(pixels, size, point(109), point(180), point(147), point(190), (244, 250, 252))
    rectangle(pixels, size, point(88), point(188), point(168), point(198), (244, 250, 252))

    # A small connector stem and rounded head suggest the USB/HID device.
    rectangle(pixels, size, point(120), point(198), point(136), point(211), (244, 250, 252))
    for y in range(point(204), point(225)):
        for x in range(point(118), point(138)):
            if (x - point(128)) ** 2 + (y - point(214)) ** 2 <= point(11) ** 2:
                pixels[y * size + x] = (244, 250, 252)
    return pixels


def write_png(path, size, pixels):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for red, green, blue in pixels[y * size : (y + 1) * size]:
            raw.extend((red, green, blue, 255))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_png(OUTPUT_DIR / "PACKAGE_ICON.PNG", 64, draw_icon(64))
    write_png(OUTPUT_DIR / "PACKAGE_ICON_256.PNG", 256, draw_icon(256))


if __name__ == "__main__":
    main()
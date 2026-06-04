"""
generate_icons.py — Generator ikon PWA (czysty Python, bez zależności)

Tworzy ikony aplikacji (gradient + linia EKG/pulsu) jako PNG.
iOS sam zaokrągla rogi, więc ikona jest pełnym, nieprzezroczystym kwadratem.

Użycie:
  python3 app/generate_icons.py
  → public/icons/icon-192.png, icon-512.png, icon-180.png
"""

from __future__ import annotations

import zlib
import struct
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"


def _lerp(a, b, t):
    return a + (b - a) * t


def render(size: int) -> bytes:
    # paleta: od indygo (góra) do turkusu (dół)
    top = (79, 70, 229)      # indigo-600
    bot = (16, 185, 129)     # emerald-500
    line = (255, 255, 255)

    px = bytearray(size * size * 3)

    def setp(x, y, c):
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 3
            px[i], px[i + 1], px[i + 2] = c

    # tło — pionowy gradient z lekką poświatą po przekątnej
    for y in range(size):
        t = y / (size - 1)
        base = tuple(int(_lerp(top[k], bot[k], t)) for k in range(3))
        for x in range(size):
            d = (x / size - 0.5)
            glow = max(0.0, 0.18 * (1 - abs(d) * 2)) * (1 - t)
            c = tuple(min(255, int(base[k] + glow * 60)) for k in range(3))
            i = (y * size + x) * 3
            px[i], px[i + 1], px[i + 2] = c

    # linia pulsu (EKG) na środku — kształt: płasko, mały ząb, duży skok, płasko
    cx = size * 0.5
    mid = size * 0.55
    amp = size * 0.16
    thickness = max(2, size // 36)
    pts = []
    n = size
    for x in range(int(size * 0.12), int(size * 0.88)):
        u = (x - size * 0.12) / (size * 0.76)  # 0..1
        # profil EKG
        if u < 0.35:
            y = mid
        elif u < 0.42:
            y = mid - amp * 0.25 * math.sin((u - 0.35) / 0.07 * math.pi)
        elif u < 0.50:
            y = mid + amp * 1.0 * math.sin((u - 0.42) / 0.08 * math.pi)
        elif u < 0.58:
            y = mid - amp * 1.3 * math.sin((u - 0.50) / 0.08 * math.pi)
        else:
            y = mid
        pts.append((x, y))

    # rysuj grubą linię przez interpolację punktów
    for k in range(len(pts) - 1):
        x0, y0 = pts[k]
        x1, y1 = pts[k + 1]
        steps = max(1, int(abs(y1 - y0)) + 1)
        for s in range(steps + 1):
            tt = s / steps
            x = int(round(_lerp(x0, x1, tt)))
            y = int(round(_lerp(y0, y1, tt)))
            for ty in range(-thickness, thickness + 1):
                # miękka krawędź
                if abs(ty) <= thickness:
                    setp(x, y + ty, line)

    # kropka na szczycie skoku
    peak = min(pts, key=lambda p: p[1])
    pr = max(3, size // 22)
    for dy in range(-pr, pr + 1):
        for dx in range(-pr, pr + 1):
            if dx * dx + dy * dy <= pr * pr:
                setp(int(peak[0]) + dx, int(peak[1]) + dy, line)

    return _encode_png(size, size, bytes(px))


def _encode_png(w: int, h: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    # dodaj bajt filtra (0) na początku każdej linii
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw.extend(rgb[y * stride:(y + 1) * stride])

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png"), (180, "icon-180.png")]:
        data = render(size)
        (OUT / name).write_bytes(data)
        print(f"[icons] {name} ({size}x{size}, {len(data)} B)")


if __name__ == "__main__":
    main()

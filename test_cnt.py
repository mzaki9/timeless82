#!/usr/bin/env python3
"""Throwaway: render N counter frames to find the firmware's max frame count."""
import sys

W, H = 128, 64
N = int(sys.argv[1]) if len(sys.argv) > 1 else 64

from PIL import Image, ImageDraw, ImageFont


def font(sz):
    try:
        return ImageFont.load_default(size=sz)
    except TypeError:
        return ImageFont.load_default()


for i in range(N):
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    big = font(48)
    sm = font(14)
    s = f"{i:02d}"
    l, t, r, b = d.textbbox((0, 0), s, font=big)
    d.text(((W - (r - l)) // 2 - l, 2), s, font=big, fill=255)
    lab = f"/ {N}"
    lw = d.textbbox((0, 0), lab, font=sm)[2]
    d.text(((W - lw) // 2, 52), lab, font=sm, fill=255)
    im = im.point(lambda v: 255 if v >= 128 else 0)
    im.save(f"cnt_{i}.png")

# pack column-major MSB-top (same as nowlive.pack_frames)
out = bytearray()
for i in range(N):
    px = Image.open(f"cnt_{i}.png").convert("L").tobytes()
    for c in range(W):
        for pg in range(H // 8):
            by = 0
            for k in range(8):
                if px[(pg * 8 + k) * W + c]:
                    by |= 1 << (7 - k)
            out.append(by)
open("cnt.bin", "wb").write(bytes(out))
print(f"wrote cnt_0..{N - 1}.png + cnt.bin ({len(out)} bytes)")

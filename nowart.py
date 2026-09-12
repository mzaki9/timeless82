#!/usr/bin/env python3
"""SMTC cover art -> dithered 1-bit image for the OLED track panel.

nowplaying.exe dumps the raw thumbnail bytes (PNG/JPEG) to a file; this
module decodes them with PIL, caches on (mtime, identity) so a playing
track's art is processed once, and dithers to the panel's 1-bit look.
Every failure path returns None, so the caller just falls back to the
full-width text layout.

Usage: nowart.py -> art_preview.png (x4 nearest, for eyeballing np_art.bin).
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "np_art.bin")
SIDE = 56
ART_X, ART_Y = 4, 4

_cache = {}


def load(path=ART, identity=""):
    """Decode the dumped thumbnail; None when missing/undecodable/stale."""
    from PIL import Image
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _cache.pop(path, None)
        return None
    key = (mtime, identity)
    if _cache.get(path, (None,))[0] == key:
        return _cache[path][1]
    try:
        with open(path, "rb") as f:
            im = Image.open(io.BytesIO(f.read()))
        im.load()
    except Exception:
        im = None
    _cache[path] = (key, im)
    return im


def art_image(im, side=SIDE):
    """1-bit panel image: square (center-cropped, not stretched so a wide
    video thumbnail is not distorted), contrast-stretched, thresholded."""
    from PIL import Image, ImageOps
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    g = im.convert("L").resize((side, side), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=1)
    return g.point(lambda v: 255 if v >= 128 else 0)


def main():
    im = load()
    if im is None:
        print(f"no art at {ART} (run: nowplaying.exe {ART})")
        return 1
    out = art_image(im)
    out.resize((out.width * 4, out.height * 4),
               Image.NEAREST).save("art_preview.png")
    print(f"art_preview.png from {os.path.basename(ART)} "
          f"(source {im.width}x{im.height} {im.mode})")
    return 0


if __name__ == "__main__":
    from PIL import Image
    sys.exit(main())

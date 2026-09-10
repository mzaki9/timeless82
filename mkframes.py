#!/usr/bin/env python3
"""Build an OLED stream (RETIRED, 21-era — kept for reference only).

The 21-slot unpacked stream format this once wrote no longer matches the
firmware wire format (30 frames x 1024B packed, column-major MSB-top).
Use nowlive.py --direct (packs 30 nowshow PNGs -> timeless82.exe oled30)
or setframes.py (30-slot unpacked JSON path). This script is untouched
apart from this notice.

Usage (historical):
  mkframes.py out.bin img1.png [img2.png img3.png img4.png] [--keep JSON]

Slots 0..k-1 come from the given images (128x64 grayscale, letterboxed);
remaining slots are preserved from the stock ScreenFrame.json so the other
screens/animations are untouched. Always writes 21 x 8192 bytes, the exact
stream proven to work with: timeless82.exe oled out.bin 21 1

After uploading, re-Apply in the stock app to restore lighting
(our CONFIG zeroes lighting bytes; standing procedure).
"""
import json
import os
import sys

W, H = 128, 64
SLOT = W * H
NSLOTS = 21

DEFAULT_KEEP = os.path.expandvars(
    r"%LOCALAPPDATA%\NoirTimeless82\keyboard\ScreenFrame.json")


def load_image(path):
    from PIL import Image
    im = Image.open(path).convert("L")
    im.thumbnail((W, H))
    canvas = Image.new("L", (W, H), 0)
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    return canvas.tobytes()


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--keep")]
    keep = DEFAULT_KEEP
    for i, a in enumerate(argv):
        if a == "--keep" and i + 1 < len(argv):
            keep = argv[i + 1]
    if len(args) < 2 or len(args) > 5:
        print(__doc__)
        return 2
    out, imgs = args[0], args[1:]
    with open(keep, encoding="utf-8-sig") as f:
        stock = json.load(f)["Frame"]
    assert len(stock) == NSLOTS and all(len(s) == SLOT for s in stock), \
        "unexpected ScreenFrame.json shape"
    stream = bytearray()
    for i in range(NSLOTS):
        if i < len(imgs):
            stream += load_image(imgs[i])
            print(f"slot {i}: {imgs[i]}")
        else:
            stream += bytes(stock[i])
    with open(out, "wb") as f:
        f.write(stream)
    print(f"wrote {out} ({len(stream)} bytes) -> "
          f"timeless82.exe oled {out} 21 1")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

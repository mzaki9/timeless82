#!/usr/bin/env python3
"""Write art into the stock app's ScreenFrame.json (slots 0..N-1, N<=30).

The stock app itself then uploads with its own correct framing AND its own
lighting bytes, so LEDs/Fn are never touched by us. Zero device writes here.

Slots are 8192B unpacked (128x64, 1 byte/px) — this is the legacy JSON
path. It writes N PNGs (dynamic count from nowshow/nowlive) into slots
0..N-1; remaining slots kept. The direct-HID path (nowlive.py --direct)
instead packs N frames to 1024B each (column-major MSB-top) and uploads
via timeless82.exe oledN. The two paths diverge by design: JSON=N
unpacked, HID=N packed.

Usage: setframes.py art0.png [art1.png ... artN.png] (N<=30)

Flow:
  1. (keyboard: stock Apply once so LEDs+screen are good, then close app)
  2. py -3 setframes.py zaki.png            # same still x4 = static
  3. open stock app -> screen page -> Apply  # stock uploads OUR frames
  4. check screen 5. Restore: copy ScreenFrame.json.bak back, Apply.
"""
import json
import os
import shutil
import sys

W, H = 128, 64
SLOT = W * H
NSLOTS = 30
JSON = os.path.expandvars(
    r"%LOCALAPPDATA%\NoirTimeless82\keyboard\ScreenFrame.json")
BAK = JSON + ".bak"


def load_art(path):
    from PIL import Image
    im = Image.open(path).convert("L")
    im.thumbnail((W, H))
    canvas = Image.new("L", (W, H), 0)
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    return list(canvas.tobytes())


def main(argv):
    arts = argv[1:]
    if not arts or len(arts) > NSLOTS or any(a.startswith("-") for a in arts):
        print(__doc__)
        return 2
    with open(JSON, encoding="utf-8-sig") as f:
        data = json.load(f)
    frames = data["Frame"]
    assert all(len(s) == SLOT for s in frames), "unexpected slot size"
    while len(frames) < len(arts):  # app compacts slots (30->7 seen); extend
        frames.append([0] * SLOT)
    nslots = len(frames)
    if not os.path.exists(BAK):
        shutil.copy2(JSON, BAK)
        print("backup:", BAK)
    else:
        print("backup exists, leaving it:", BAK)
    for i, a in enumerate(arts):
        frames[i] = load_art(a)
        print(f"slot {i}: {a}")
    for i in range(len(arts), NSLOTS):
        frames[i] = list(frames[i])  # keep existing
    with open(JSON, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"wrote {JSON} ({nslots} slots kept)")
    print("next: open stock app -> screen page -> Apply, check screen 5")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""Render 4-frame 128x64 OLED animations for screen 5.

Usage: mkanim.py {bounce,scroll,eq,stars} [text] -> anim_<name>_<i>.png (x4)

Frames are grayscale; white = lit. Feed them to mkframes.py, e.g.:
  py -3 mkanim.py bounce
  py -3 mkframes.py bounce21.bin anim_bounce_0.png anim_bounce_1.png \\
      anim_bounce_2.png anim_bounce_3.png
"""
import math
import sys

W, H = 128, 64


def new():
    from PIL import Image, ImageDraw
    im = Image.new("L", (W, H), 0)
    return im, ImageDraw.Draw(im)


def ball(d, cx, cy, r, fill=255):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def bounce():
    frames = []
    for i in range(4):
        im, d = new()
        t = i / 4.0
        cx = int(20 + 88 * t)
        cy = int(32 - 22 * math.sin(t * math.pi))
        for k in range(1, 4):  # trail
            tk = t - k * 0.06
            if tk < 0:
                continue
            ball(d, int(20 + 88 * tk), int(32 - 22 * math.sin(tk * math.pi)),
                 8, fill=60)
        ball(d, cx, cy, 9)
        d.rectangle([0, 0, W - 1, H - 1], outline=255)
        frames.append(im)
    return frames


def scroll(text="TIMELESS 82", n=8, step=None):
    from PIL import ImageFont
    font = ImageFont.load_default(size=22)
    tmp, d0 = new()
    tw = textw(d0, text, font)
    total = tw + W + 32
    step = total / n if step is None else step
    frames = []
    for i in range(n):
        im, d = new()
        x = W + 16 - i * step
        d.text((int(x), 20), text, font=font, fill=255)
        d.rectangle([0, 0, W - 1, H - 1], outline=255)
        im = im.point(lambda v: 255 if v >= 128 else 0)
        frames.append(im)
    return frames


def eq():
    frames = []
    for i in range(4):
        im, d = new()
        for b in range(16):
            h = int(28 + 26 * math.sin(i * 1.7 + b * 0.9))
            x0 = 4 + b * 8
            d.rectangle([x0, 60 - h, x0 + 5, 60], fill=255)
        frames.append(im)
    return frames


def name(text="ZAKi"):
    from PIL import ImageFont
    font = ImageFont.load_default(size=40)
    frames = []
    for i in range(4):
        im, d = new()
        # centered text
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        tw, th = r - l, b - t
        d.text(((W - tw) // 2, (H - th) // 2 - 4), text, font=font, fill=255)
        # sweeping underline + blinking corners
        ux = 14 + i * 26
        d.line([(ux, 54), (ux + 18, 54)], fill=255, width=2)
        if i % 2 == 0:
            for cx, cy in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
                d.rectangle([cx - 2 if cx else cx, cy - 2 if cy else cy,
                             cx + 2 if cx < W - 1 else cx,
                             cy + 2 if cy < H - 1 else cy], outline=255)
        else:
            d.rectangle([0, 0, W - 1, H - 1], outline=255)
        frames.append(im)
    return frames


def stars():
    import random
    rng = random.Random(7)
    pts = [(rng.randrange(W), rng.randrange(H), (n % 3) + 1)
           for n in range(60)]
    frames = []
    for i in range(4):
        im, d = new()
        for x, y, sp in pts:
            xx = (x + i * sp * 3) % W
            d.point((xx, y), fill=255)
            if sp == 3:
                d.point(((xx + 1) % W, y), fill=255)
        frames.append(im)
    return frames


def main(argv):
    which = argv[1] if len(argv) > 1 else "bounce"
    makers = {"bounce": lambda: bounce(),
              "name": lambda: name(argv[2] if len(argv) > 2 else "ZAKi"),
              "scroll": lambda: scroll(argv[2] if len(argv) > 2 else "TIMELESS 82"),
              "eq": eq, "stars": stars}
    if which not in makers:
        print(__doc__)
        return 2
    frames = makers[which]()
    outs = []
    for i, im in enumerate(frames):
        p = f"anim_{which}_{i}.png"
        im.save(p)
        outs.append(p)
    print("wrote", " ".join(outs))
    print("next: py -3 mkframes.py", f"{which}21.bin", " ".join(outs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

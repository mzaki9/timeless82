#!/usr/bin/env python3
"""Render current Windows media into Nx 128x64 OLED frames (running text).

Usage: nowshow.py -> anim_np_0..N-1.png (then deliver via setframes.py
or nowlive.py --direct pack+upload). Stale anim_np_*.png >= N are deleted.

Layout: top status bar (play state left, date right), one scrolling line
"Title - Artist" running left at constant speed with wraparound. Idle
(nothing playing): centered date. No clock content, so frames never go
stale: the loop re-uploads only when the track/state changes. Short text
renders identical static frames (no pointless motion).

Scroll: dynamic frame count. L=tw+GAPp (text + blank gap). The device
plays at a fixed rate, so speed = STEP px/frame; to slow the marquee we
use as many frames as the hardware allows (MAXN=128, verified) with the
smallest integer STEP, N=ceil((tw+MIN_GAP)/STEP). N*STEP == L exactly, so
hypothetical frameN renders byte-identical to frame0: zero loop snap,
zero mid-loop cut (copy-fill draws k from negative so the right-entering
copy is never missing).
"""
import math
import subprocess
import sys
from datetime import datetime

W, H = 128, 64
MAXN = 128  # hardware frame cap (verified: 128 frames play, 129+ wraps; CONFIG nframes byte)
MIN_GAP = 32
STATIC_N = 4
X0 = 4  # small left margin for scroll start
NP = r"D:\Project\keyboard\timeless82\nowplaying\bin\Release\net8.0-windows10.0.22621.0\nowplaying.exe"


def font(sz):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=sz)
    except TypeError:
        return ImageFont.load_default()


def textw(d, s, f):
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return r - l


def pick_plan(tw):
    """Frame count for the slowest seamless loop.

    The device plays frames at a fixed rate, so speed == STEP px/frame;
    the only way to slow down is more frames at a smaller STEP. Use as
    many frames as the hardware cap allows: STEP = ceil((tw+MIN_GAP)/MAXN),
    then N = ceil((tw+MIN_GAP)/STEP) (<= MAXN). Returns (n, step, gap) with
    n*step == tw+gap exactly, so hypothetical frameN renders byte-identical
    to frame0 (zero loop snap). gap lands in [MIN_GAP, MIN_GAP+step).
    """
    if tw <= W - 4:
        return STATIC_N, 0, 0  # static: no motion
    step = max(1, math.ceil((tw + MIN_GAP) / MAXN))
    n = math.ceil((tw + MIN_GAP) / step)
    return n, step, n * step - tw


def new():
    from PIL import Image, ImageDraw
    im = Image.new("L", (W, H), 0)
    return im, ImageDraw.Draw(im)


def render_idle():
    date = datetime.now().strftime("%a %d %b").upper()
    frames = []
    for i in range(STATIC_N):
        im, d = new()
        f = font(20)
        d.text(((W - textw(d, date, f)) // 2, 22), date, font=f, fill=255)
        frames.append(im)
    return frames, "idle", 0, 0, STATIC_N


def render_track(title, artist, playing):
    tmp_im, tmp_d = new()
    fl = font(20)
    fi = font(12)
    combo = title + (" - " + artist if artist else "")
    tw = textw(tmp_d, combo, fl)
    date = datetime.now().strftime("%a %d %b").upper()
    status = ("> " if playing else "|| ") + ("PLAYING" if playing else "PAUSED")
    n, step, gap_used = pick_plan(tw)
    L = tw + gap_used
    frames = []
    for i in range(n):
        im, d = new()
        d.text((2, 1), status, font=fi, fill=255)
        dw = textw(d, date, fi)  # date top-right, where the clock used to be
        d.text((W - 2 - dw, 1), date, font=fi, fill=255)
        d.line([(0, 15), (W - 1, 15)], fill=255)
        if step == 0:
            d.text(((W - tw) // 2, 22), combo, font=fl, fill=255)
        else:
            x = X0 - i * step
            k = math.floor((0 - x - tw) / L)
            while x + k * L < W:
                if x + k * L + tw > 0:
                    d.text((x + k * L, 22), combo, font=fl, fill=255)
                k += 1
        frames.append(im)
    return frames, combo, step, gap_used, n


def get_frames():
    """Poll media + render. Returns (bw_frames, meta dict). Import-safe."""
    try:
        out = subprocess.run([NP], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError("media poll timeout (SMTC hung?)")
    if not out or out == "NO-SESSION":
        frames, what, step, gap_used, n = render_idle()
    else:
        status, title, artist = (out.split("\t") + ["", ""])[:3]
        if not title:
            frames, what, step, gap_used, n = render_idle()
        else:
            frames, what, step, gap_used, n = render_track(
                title or "?", artist or "?", status == "Playing")
    bw = [im.point(lambda v: 255 if v >= 128 else 0) for im in frames]  # pure B/W
    meta = {"what": what, "n": n, "step": step, "gap": gap_used}
    return bw, meta


def main():
    import glob
    import os
    import time
    t0 = time.time()
    try:
        frames, meta = get_frames()
    except RuntimeError as e:
        print(f"media poll failed: {e} (keyboard keeps last frames)")
        return 1
    n = meta["n"]
    names = []
    for i, im in enumerate(frames):
        p = f"anim_np_{i}.png"
        im.save(p)
        names.append(p)
    for stale in glob.glob("anim_np_*.png"):  # del count beyond N
        try:
            idx = int(stale[len("anim_np_"):-len(".png")])
        except ValueError:
            continue
        if idx >= n:
            os.remove(stale)
    dt = time.time() - t0
    print("showing:", meta["what"])
    print("wrote", " ".join(names))
    print(f"frames: {n} STEP={meta['step']} GAPp={meta['gap']} "
          f"render_time={dt:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

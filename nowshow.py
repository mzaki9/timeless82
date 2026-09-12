#!/usr/bin/env python3
"""Render current Windows media into Nx 128x64 OLED frames (running text).

Usage: nowshow.py -> anim_np_0..N-1.png (then deliver via setframes.py
or nowlive.py --direct pack+upload). Stale anim_np_*.png >= N are deleted.

Layout: top status bar (play state left, date right), one scrolling line
"Title - Artist" running left at constant speed with wraparound. Idle
(nothing playing): big clock + date card, re-uploaded once a minute by
nowlive. With cover art the track layout is 2-column: 56x56 dithered art at
(4,4), narrower scrolling title/artist column to its right; without art the
text keeps the full width. Short text renders identical static frames (no
pointless motion).

Scroll: dynamic frame count. L=tw+GAPp (text + blank gap). The device
plays at a fixed rate, so speed = STEP px/frame; to slow the marquee we
use as many frames as the hardware allows (MAXN=128, verified) with the
smallest integer STEP, N=ceil((tw+MIN_GAP)/STEP). N*STEP == L exactly, so
hypothetical frameN renders byte-identical to frame0: zero loop snap,
zero mid-loop cut (copy-fill draws k from negative so the right-entering
copy is never missing).
"""
import math
import os
import subprocess
import sys
from datetime import datetime

W, H = 128, 64
MAXN = 128  # hardware frame cap (verified: 128 frames play, 129+ wraps; CONFIG nframes byte)
MIN_GAP = 32
STATIC_N = 4
X0 = 4  # small left margin for scroll start
HERO_Y = 18  # title scroll top
ART_Y = 46  # artist line top
ARTB_X, ARTB_Y = 4, 4  # cover-art box origin (56x56, art column layout)
NP = r"D:\Project\keyboard\timeless82\nowplaying\bin\Release\net8.0-windows10.0.22621.0\nowplaying.exe"
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def font(sz):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, "arialbd.ttf"), sz)
    except (OSError, TypeError):
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()


def textw(d, s, f):
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return r - l


def pick_plan(tw, maxn=MAXN, maxw=W - 4):
    """Frame count for the slowest seamless loop within a frame budget.

    The device plays frames at a fixed rate, so speed == STEP px/frame;
    the only way to slow down is more frames at a smaller STEP. But the
    upload (and its keyboard freeze) is ~65ms per frame, so maxn caps the
    cost: STEP = ceil((tw+MIN_GAP)/maxn), then N = ceil((tw+MIN_GAP)/STEP)
    (<= maxn). Returns (n, step, gap) with n*step == tw+gap exactly, so
    hypothetical frameN renders byte-identical to frame0 (zero loop snap).
    gap lands in [MIN_GAP, MIN_GAP+step). maxw = text width that still fits
    static (no motion).
    """
    if tw <= maxw:
        return STATIC_N, 0, 0  # static: no motion
    maxn = max(1, min(maxn, MAXN))
    step = max(1, math.ceil((tw + MIN_GAP) / maxn))
    n = math.ceil((tw + MIN_GAP) / step)
    return n, step, n * step - tw


def new():
    from PIL import Image, ImageDraw
    im = Image.new("L", (W, H), 0)
    return im, ImageDraw.Draw(im)


def render_idle():
    """Big local clock + date card. Re-uploaded once a minute by nowlive."""
    now = datetime.now()
    hhmm = now.strftime("%H:%M")
    date = now.strftime("%a %d %b %Y").upper()
    frames = []
    for i in range(STATIC_N):
        im, d = new()
        f = font(34)
        d.text((14 + (112 - textw(d, hhmm, f)) // 2, 8), hhmm, font=f, fill=255)
        f2 = font(10)
        d.text((14 + (112 - textw(d, date, f2)) // 2, 52), date, font=f2, fill=255)
        frames.append(im)
    return frames, "idle", 0, 0, STATIC_N


def state_glyph(d, playing, x=3, y=2):
    """Drawn transport glyph: filled right triangle (play) or two bars (pause)."""
    if playing:
        d.polygon([(x, y), (x, y + 9), (x + 7, y + 4)], fill=255)
    else:
        d.rectangle([x, y, x + 2, y + 9], fill=255)
        d.rectangle([x + 5, y, x + 7, y + 9], fill=255)


def fit_text(d, s, f, maxw):
    """Ellipsize s with '...' until it fits maxw."""
    if textw(d, s, f) <= maxw:
        return s
    while s and textw(d, s + "...", f) > maxw:
        s = s[:-1]
    return (s + "...") if s else ""


def render_track(title, artist, playing, maxn=MAXN, art=None):
    """Scrolling title (+ artist). art = dithered 56x56 image -> 2-column
    layout: art left, narrower scrolling column right. Without art the text
    uses the full width.
    """
    from PIL import Image, ImageDraw
    tmp_im, tmp_d = new()
    col = art is not None
    fl = font(14 if col else 16)
    fi = font(10)
    fa = font(10 if col else 11)
    tx = 64 if col else 0  # text column origin
    colw = 64 if col else W
    tw = textw(tmp_d, title, fl)
    date = datetime.now().strftime("%d %b" if col else "%a %d %b").upper()
    n, step, gap_used = pick_plan(tw, maxn, 60 if col else W - 4)
    L = tw + gap_used
    frames = []
    for i in range(n):
        im, d = new()
        if col:
            im.paste(art, (ARTB_X, ARTB_Y))
        state_glyph(d, playing, tx, 2)
        dw = textw(d, date, fi)
        d.text((W - 3 - dw, 1), date, font=fi, fill=255)
        d.line([(tx, 14), (W - 1, 14)], fill=255)
        # Scroll inside a column-sized scratch strip: drawing straight onto
        # the frame would let the title run under the art.
        strip = Image.new("L", (colw, H - HERO_Y), 0)
        sd = ImageDraw.Draw(strip)
        if step == 0:
            sd.text((max(1, (colw - tw) // 2), 0), title, font=fl, fill=255)
        else:
            x = (X0 + 1 if col else X0) - i * step
            k = math.floor((0 - x - tw) / L)
            while x + k * L < colw:
                if x + k * L + tw > 0:
                    sd.text((x + k * L, 0), title, font=fl, fill=255)
                k += 1
        im.paste(strip, (tx, HERO_Y))
        a = fit_text(d, artist, fa, colw - 2)
        aw = textw(d, a, fa)
        d.text((tx + max(1, (colw - aw) // 2), ART_Y), a, font=fa, fill=255)
        frames.append(im)
    return frames, title, step, gap_used, n


def get_frames(maxn=MAXN, art=None):
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
                title or "?", artist or "?", status == "Playing", maxn, art)
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

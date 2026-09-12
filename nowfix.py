#!/usr/bin/env python3
"""Stuck-pixel / image-retention repair panel for the 128x64 OLED.

A stuck pixel is a cell latched on (or off) that ordinary content never
exercises. Any single still leaves that cell exactly as it already was, so the
remedy is to drive the whole panel to the opposite extreme instead: full-field
black then full-field white, repeated.

Every frame here is a uniform field, so every one of the 8192 pixels is driven
hard and toggled as the device replays the set. The device loops N frames on
its own with no host involved, so the cycle keeps running (and keeps the
keyboard responsive) for as long as the panel is on screen: one ~0.7s upload
is the entire cost. Phase order black -> white -> black -> white, so the set
both opens and closes on black (the safe resting state) and no white frame
directly follows another white frame.

Cycling R/G/B full-field flashes - the usual LCD trick - is deliberately not
offered: this panel is 1-bit monochrome, so any non-grey field renders
identically to white and would only add frames to the upload.

Usage: py -3 nowfix.py [--frames N]        (dry render, no device writes)
       py -3 nowlive.py --once --direct --mode fix [--fixsec N]
"""
import sys

HERE = r"D:\Project\keyboard\timeless82"
sys.path.insert(0, HERE)
import nowshow  # noqa: E402  (shares W, H, new(), and the pack order)

W, H = nowshow.W, nowshow.H
FIX_SEC = 30  # seconds a --mode fix loop holds the pattern before np resumes
PHASE_MS = 250  # device ms per phase: 1s loop = 2 full black+white cycles/s
PHASES = (0, 255, 0, 255)  # black, white, black, white


def fields():
    """The two uniform full-screen fields, in device pixel values."""
    black, _ = nowshow.new()
    white, _ = nowshow.new()
    white.paste(255, (0, 0, W, H))
    return black, white


def render():
    """One frame per phase: 4 uniform frames, alternating black/white.

    The meta carries an explicit interval so the device paces the cycle
    itself: at PHASE_MS per frame the 4-frame set is one second long, i.e. a
    full black+white cycle twice a second for as long as the panel is up.
    Without it a step-0 render falls back to 1000ms per frame and wastes the
    repair on 4-second phases.
    """
    black, white = fields()
    return [black if p == 0 else white for p in PHASES], \
        {"what": "fix", "n": len(PHASES), "step": 0, "gap": 0,
         "interval": PHASE_MS}


def main(argv):
    n = len(PHASES)
    args = list(argv[1:])
    if "--frames" in args:
        v = args[args.index("--frames") + 1]
        n = min(max(int(v), 2), nowshow.MAXN)
    black, white = fields()
    imgs = [black if i % 2 == 0 else white for i in range(n)]
    names = []
    for i, im in enumerate(imgs):
        p = f"anim_fix_{i}.png"
        im.save(p)
        names.append(p)
    print("wrote", " ".join(names))
    print(f"fix panel: {n} frames alternating black/white at {PHASE_MS}ms each "
          f"= {n * PHASE_MS / 1000:.1f}s loop; nowlive holds it {FIX_SEC}s "
          f"(--fixsec), then hands the preference back to auto")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

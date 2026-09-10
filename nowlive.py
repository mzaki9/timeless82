#!/usr/bin/env python3
"""Live now-playing -> OLED frames, two delivery paths.

JSON path (default, no HID): polls the current media session; when the
track/state changes, re-renders N frames via nowshow.py (dynamic count:
STATIC_N..MAXN) and updates slots 0..N-1 of ScreenFrame.json via
setframes.py. If the stock app picks up file changes on its own, the
screen follows with zero clicks; otherwise one manual Apply refreshes it.

Direct path (--direct): imports nowshow (same process, no subprocess),
packs Nx1024B bin (column-major MSB-top) and uploads with
timeless82.exe oledN (screen 5 = disp 4, interval slows the scroll).
--dry renders (+packs in direct mode) without uploading or touching JSON.
--interval MS sets frame interval (default 150; larger = slower).
--disp I sets screen index (default 4 = screen 5).

Usage: nowlive.py [--once] [--direct] [--dry] [--interval MS] [--disp I] [interval_sec=5]
"""
import subprocess
import sys
import time

HERE = r"D:\Project\keyboard\timeless82"
NP = HERE + r"\nowplaying\bin\Release\net8.0-windows10.0.22621.0\nowplaying.exe"
EXE = HERE + r"\timeless82.exe"
BIN = HERE + r"\npN.bin"
W, H = 128, 64
MAXN = 30
DISP = 4  # 0-based screen index: 4 = screen 5 (user anim)
INTERVAL = 150  # frame interval ms (CONFIG[43..44] u16 LE): larger = slower

sys.path.insert(0, HERE)
import nowshow


def current():
    try:
        out = subprocess.run([NP], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] err poll: {e}", flush=True)
        return "ERR"  # stable token: no refresh storm
    return out or "EMPTY"


def pack_frames(frames):
    """Pack N 128x64 1B/px frames -> Nx1024B wire bin.

    Column-major MSB-top: byte[c*8+pg], bit 7-k = pixel (pg*8+k, c).
    """
    from PIL import Image
    out = bytearray()
    for im in frames:
        px = im.convert("L").tobytes()
        assert len(px) == W * H, f"bad size {len(px)}"
        for c in range(W):
            for pg in range(H // 8):
                b = 0
                for k in range(8):
                    if px[(pg * 8 + k) * W + c]:
                        b |= 1 << (7 - k)
                out.append(b)
    assert frames, "no input frames"
    assert len(out) == len(frames) * 1024, len(out)
    return bytes(out)


def refresh_json():
    t0 = time.time()
    try:
        frames, meta = nowshow.get_frames()
        import os
        for i, im in enumerate(frames):
            im.save(HERE + rf"\anim_np_{i}.png")
        n = meta["n"]
        for stale in __import__("glob").glob(HERE + r"\anim_np_*.png"):
            try:
                idx = int(stale[len(HERE + r"\anim_np_"):-len(".png")])
            except ValueError:
                continue
            if idx >= n:
                os.remove(stale)
        pngs = [HERE + rf"\anim_np_{i}.png" for i in range(n)]
        r2 = subprocess.run([sys.executable, HERE + r"\setframes.py"] + pngs,
                            check=True, capture_output=True, text=True,
                            timeout=60, cwd=HERE)
    except subprocess.CalledProcessError as e:
        print(f"refresh failed rc={e.returncode}: {(e.stderr or e.stdout or '')[-500:]}",
              flush=True)
        return False
    except Exception as e:
        print(f"refresh failed: {e}", flush=True)
        return False
    ms = int((time.time() - t0) * 1000)
    print(f"frames+json updated n={meta['n']} ({ms}ms)", flush=True)
    return True


def refresh_direct(dry=False, disp=DISP, interval=INTERVAL):
    """Render in-process -> pack N frames -> optional oledN upload."""
    t0 = time.time()
    try:
        frames, meta = nowshow.get_frames()
        n = meta["n"]
        import os
        for i, im in enumerate(frames):
            im.save(HERE + rf"\anim_np_{i}.png")
        for stale in __import__("glob").glob(HERE + r"\anim_np_*.png"):
            try:
                idx = int(stale[len(HERE + r"\anim_np_"):-len(".png")])
            except ValueError:
                continue
            if idx >= n:
                os.remove(stale)
        bin_bytes = pack_frames(frames)
        with open(BIN, "wb") as f:
            f.write(bin_bytes)
        if dry:
            ms = int((time.time() - t0) * 1000)
            print(f"rendered+packed dry n={n} ({ms}ms) -> {BIN}", flush=True)
            return True
        r2 = subprocess.run([EXE, "oledN", BIN, str(n), str(disp),
                             str(interval)],
                            check=True, capture_output=True, text=True,
                            timeout=120, cwd=HERE)
    except subprocess.CalledProcessError as e:
        print(f"refresh-direct failed rc={e.returncode}: "
              f"{(e.stderr or e.stdout or '')[-500:]}", flush=True)
        return False
    except Exception as e:
        print(f"refresh-direct failed: {e}", flush=True)
        return False
    ms = int((time.time() - t0) * 1000)
    print(f"direct upload done n={n} disp={disp} interval={interval} ({ms}ms)", flush=True)
    return True


def refresh_dry_json():
    """Render only (no JSON write, no upload)."""
    try:
        frames, meta = nowshow.get_frames()
        for i, im in enumerate(frames):
            im.save(HERE + rf"\anim_np_{i}.png")
    except Exception as e:
        print(f"dry render failed: {e}", flush=True)
        return False
    print(f"rendered dry n={meta['n']} (json untouched)", flush=True)
    return True


def main(argv):
    once = "--once" in argv
    direct = "--direct" in argv
    dry = "--dry" in argv
    disp, interval = DISP, INTERVAL
    args = list(argv[1:])
    for i, a in enumerate(args):
        if a == "--disp" and i + 1 < len(args) and args[i + 1].isdigit():
            disp = min(max(int(args[i + 1]), 0), 5)
        if a in ("--interval", "--speed") and i + 1 < len(args) and args[i + 1].isdigit():
            interval = min(max(int(args[i + 1]), 1), 60000)
        if a.startswith("--interval=") and a.split("=", 1)[1].isdigit():
            interval = min(max(int(a.split("=", 1)[1]), 1), 60000)
    poll = 5
    for a in argv[1:]:
        if a.isdigit():
            poll = min(max(int(a), 1), 300)
    print(f"poll every {poll}s, --once={once} --direct={direct} "
          f"--dry={dry} disp={disp} interval={interval}", flush=True)
    last = None
    last_tick_min = None
    refresh = (lambda: refresh_direct(dry, disp, interval)) if direct else \
              (refresh_dry_json if dry else refresh_json)
    while True:
        try:
            cur = current()
            now_min = time.strftime("%H:%M")
            tick = (cur != last) or (now_min != last_tick_min and cur != "ERR")
            # ponytail: clock baked into frames goes stale within the minute.
            # Refresh on minute flip keeps it ticking. Upgrade path: overlay
            # clock at upload time instead of re-rendering all frames.
            if tick:
                if cur != "ERR":
                    print(f"[{time.strftime('%H:%M:%S')}] change: {cur[:80]}",
                          flush=True)
                    if refresh():
                        last = cur
                        last_tick_min = now_min
                else:
                    time.sleep(poll)
                    if once:
                        return 0
                    continue
        except Exception:
            import traceback
            traceback.print_exc()
        if once:
            return 0
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

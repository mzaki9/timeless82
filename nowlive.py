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
Scroll pace = STEP px per frame interval (CONFIG[39..40], now live). The loop
derives the interval from --speed PXPS (default 110) so a smaller frame budget
keeps the same pace instead of racing; --interval MS pins a fixed interval
instead. --disp I sets screen index (default 4 = screen 5).
--maxn N caps frames (1..128, default 32): lower = smaller upload, shorter
keyboard freeze (~65ms/frame), chunkier motion. Track changes are debounced
(2s settle) so rapid skipping = one upload, not many.
The board's firmware stalls keyboard scanning while it ingests a display
upload (~65ms per frame), so a running loop uploads only when the user is
idle: it waits for no keyboard/mouse input for --idle-ms (default 1500)
before starting, and defers otherwise. --once uploads immediately.

Usage: nowlive.py [--once] [--direct] [--dry] [--speed PXPS] [--interval MS] [--disp I] [--idle-ms N] [--maxn N] [--mode np|sys|auto] [--syssec N] [interval_sec=5]

Panels (--mode, persisted in tray.mode, chosen from the tray Screen menu):
`np` = now playing, or the clock/date card when nothing plays; `sys` =
system monitor (CPU/GPU bars + RAM/temp/battery/net/disk); `auto` = `np`
while a track plays, `sys` while idle. The sys panel re-uploads every
--syssec seconds (default 5) because its values are live; the clock card
re-uploads once a minute. Album art is dumped by nowplaying.exe to np_art.bin
and used when the session has a thumbnail.
"""
import subprocess
import sys
import time

HERE = r"D:\Project\keyboard\timeless82"
NP = HERE + r"\nowplaying\bin\Release\net8.0-windows10.0.22621.0\nowplaying.exe"
EXE = HERE + r"\timeless82.exe"
BIN = HERE + r"\npN.bin"
W, H = 128, 64
MAXN = 128  # hardware playback cap (verified: 128 plays, 129+ wraps)
MAXN_DEFAULT = 32  # default frame budget: short upload, short keyboard freeze
DISP = 4  # 0-based screen index: 4 = screen 5 (user anim)
SPEED = 110  # target scroll pace px/s; the frame interval is derived from it
INTERVAL = None  # explicit --interval MS override; None = derive from SPEED
IDLE_MS = 1500  # only start an upload after this long with no keyboard/mouse
DEBOUNCE = 2.0  # settle time before uploading (collapses rapid track skips)
MODES = ("np", "sys", "auto")  # np = media/clock, sys = system monitor
MODE_DEFAULT = "auto"  # auto: sys while nothing plays, np otherwise
SYS_SEC = 5  # system panel re-upload cadence (seconds)
ART = HERE + r"\np_art.bin"  # thumbnail dump target handed to nowplaying.exe
NP_ARGS = [NP, ART]

sys.path.insert(0, HERE)
import nowart
import nowshow
import nowsys
from datetime import datetime


def idle_ms():
    """Milliseconds since the last keyboard/mouse input in this session."""
    import ctypes

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    li = LII()
    li.cbSize = ctypes.sizeof(li)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 1 << 30
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0x7FFFFFFF


def current():
    try:
        out = subprocess.run(NP_ARGS, capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] err poll: {e}", flush=True)
        return "ERR"  # stable token: no refresh storm
    return out or "EMPTY"


def has_track(cur):
    return bool(cur) and cur not in ("EMPTY", "NO-SESSION") and \
        bool((cur.split("\t") + [""])[1])


def panel_for(cur, mode):
    """Which panel this tick should show."""
    if mode in ("np", "sys"):
        return mode
    return "np" if has_track(cur) else "sys"


def change_key(panel, cur, sys_sec=SYS_SEC):
    """What an upload depends on: the only thing that re-uploads a panel."""
    if panel == "sys":
        return ("sys", "", int(time.time() // sys_sec))
    if not has_track(cur):
        # Clock card: the device loops one upload, so tick it once a minute.
        return ("np", "", datetime.now().strftime("%H:%M"))
    return ("np", cur, 0)


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


def render_frames(panel, maxn=MAXN, pdh=None):
    """Render the selected panel. Returns (frames, meta); may raise."""
    if panel == "sys":
        return nowsys.render(nowsys.sample(pdh))
    src = nowart.load(ART)
    return nowshow.get_frames(maxn, nowart.art_image(src) if src else None)


def save_pngs(frames, n):
    import glob
    import os
    for i, im in enumerate(frames):
        im.save(HERE + rf"\anim_np_{i}.png")
    for stale in glob.glob(HERE + r"\anim_np_*.png"):
        try:
            idx = int(stale[len(HERE + r"\anim_np_"):-len(".png")])
        except ValueError:
            continue
        if idx >= n:
            os.remove(stale)


def refresh_json(maxn=MAXN, panel="np", pdh=None):
    t0 = time.time()
    try:
        frames, meta = render_frames(panel, maxn, pdh)
        save_pngs(frames, meta["n"])
        n = meta["n"]
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


def refresh_direct(dry=False, disp=DISP, interval=INTERVAL, maxn=MAXN,
                   speed=SPEED, panel="np", pdh=None):
    """Render in-process -> pack N frames -> optional oledN upload.

    interval=None derives the device frame interval from the render's STEP and
    the target speed, so shrinking --maxn costs smoothness, not pace.
    """
    t0 = time.time()
    try:
        frames, meta = render_frames(panel, maxn, pdh)
        n = meta["n"]
        save_pngs(frames, n)
        bin_bytes = pack_frames(frames)
        with open(BIN, "wb") as f:
            f.write(bin_bytes)
        if dry:
            ms = int((time.time() - t0) * 1000)
            print(f"rendered+packed dry n={n} ({ms}ms) -> {BIN}", flush=True)
            return True
        step = meta["step"]
        # Only a scrolling render has a STEP to spread over an interval; a
        # static frame ignores it, so 1000 just keeps the value sane.
        iv = interval or (round(step * 1000 / speed) if step else 1000)
        iv = min(max(int(iv), 1), 60000)
        r2 = subprocess.run([EXE, "oledN", BIN, str(n), str(disp), str(iv)],
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
    print(f"direct upload done n={n} step={step} disp={disp} interval={iv}ms "
          f"({ms}ms upload, {n * iv / 1000:.1f}s loop)", flush=True)
    return True


def refresh_dry_json(maxn=MAXN, panel="np", pdh=None):
    """Render only (no JSON write, no upload)."""
    try:
        frames, meta = render_frames(panel, maxn, pdh)
        save_pngs(frames, meta["n"])
    except Exception as e:
        print(f"dry render failed: {e}", flush=True)
        return False
    print(f"rendered dry n={meta['n']} (json untouched)", flush=True)
    return True


def main(argv):
    once = "--once" in argv
    direct = "--direct" in argv
    dry = "--dry" in argv
    disp, interval, idle_gate, maxn = DISP, INTERVAL, IDLE_MS, MAXN_DEFAULT
    speed = SPEED
    mode, sys_sec = MODE_DEFAULT, SYS_SEC
    poll = 5
    args = list(argv[1:])
    i = 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a == "--disp" and nxt.isdigit():
            disp = min(max(int(nxt), 0), 5); i += 2; continue
        if a == "--interval" and nxt.isdigit():
            interval = min(max(int(nxt), 1), 60000); i += 2; continue
        if a == "--speed" and nxt.isdigit():
            speed = min(max(int(nxt), 1), 10000); i += 2; continue
        if a in ("--idle-ms", "--idle") and nxt.isdigit():
            idle_gate = min(max(int(nxt), 0), 600000); i += 2; continue
        if a in ("--maxn", "--frames") and nxt.isdigit():
            maxn = min(max(int(nxt), 1), MAXN); i += 2; continue
        if a == "--mode" and nxt in MODES:
            mode = nxt; i += 2; continue
        if a == "--syssec" and nxt.isdigit():
            sys_sec = min(max(int(nxt), 1), 300); i += 2; continue
        if a.startswith("--interval=") and a.split("=", 1)[1].isdigit():
            interval = min(max(int(a.split("=", 1)[1]), 1), 60000)
        elif a.startswith("--speed=") and a.split("=", 1)[1].isdigit():
            speed = min(max(int(a.split("=", 1)[1]), 1), 10000)
        elif a.startswith("--idle-ms=") and a.split("=", 1)[1].isdigit():
            idle_gate = min(max(int(a.split("=", 1)[1]), 0), 600000)
        elif a.startswith("--maxn=") and a.split("=", 1)[1].isdigit():
            maxn = min(max(int(a.split("=", 1)[1]), 1), MAXN)
        elif a.startswith("--mode=") and a.split("=", 1)[1] in MODES:
            mode = a.split("=", 1)[1]
        elif a.startswith("--syssec=") and a.split("=", 1)[1].isdigit():
            sys_sec = min(max(int(a.split("=", 1)[1]), 1), 300)
        elif a.isdigit():
            poll = min(max(int(a), 1), 300)  # bare positional = poll seconds
        i += 1
    # The device is unusable while an upload is in flight, so only gate the
    # real direct upload in loop mode. --once and JSON/dry paths upload now.
    gate_upload = direct and not dry and not once and idle_gate > 0
    debounce = 0.0 if once else DEBOUNCE
    print(f"poll every {poll}s, --once={once} --direct={direct} "
          f"--dry={dry} disp={disp} interval={interval or 'auto'} "
          f"speed={speed}px/s maxn={maxn} mode={mode} syssec={sys_sec} "
          f"idle_gate={'on' if gate_upload else 'off'}"
          + (f" ({idle_gate}ms)" if gate_upload else ""), flush=True)
    pdh = None
    if not dry:
        try:
            pdh = nowsys.Pdh()
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] sys panel unavailable: {e}",
                  flush=True)
    last = None
    pending = None
    pending_at = 0.0

    def refresh(panel):
        if direct:
            return refresh_direct(dry, disp, interval, maxn, speed, panel, pdh)
        if dry:
            return refresh_dry_json(maxn, panel, pdh)
        return refresh_json(maxn, panel, pdh)

    while True:
        try:
            cur = current()
            if cur == "ERR":
                time.sleep(poll)
                if once:
                    return 0
                continue
            panel = panel_for(cur, mode)
            if panel == "sys" and pdh is None:
                try:
                    pdh = nowsys.Pdh()
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] sys panel failed: {e}",
                          flush=True)
                    panel = "np"  # this tick only; the next one retries
            key = change_key(panel, cur, sys_sec)
            # Frames stay valid while nothing changes: the device loops one
            # upload. Debounce settles rapid track skips into one upload, so it
            # keys on panel+content only: the sys time bucket changes every
            # tick and must not restart the settle window.
            if key != last:
                if key[:2] != pending:
                    pending = key[:2]
                    pending_at = time.time()
                # The settle window exists to collapse rapid track skipping;
                # the sys panel is time-bucketed and has nothing to collapse.
                if (time.time() - pending_at) >= (0.0 if panel == "sys" else debounce):
                    if gate_upload and idle_ms() < idle_gate:
                        print(f"[{time.strftime('%H:%M:%S')}] deferred "
                              f"(input {idle_ms()}ms ago, need {idle_gate}ms)",
                              flush=True)
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] change: {key}",
                              flush=True)
                        if refresh(panel):
                            last = key
                            pending = None
        except Exception:
            import traceback
            traceback.print_exc()
        if once:
            return 0
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

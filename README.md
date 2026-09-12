# Timeless82 v1 — Windows CLI for LED control (Path A)

No custom firmware. No flashing. Stock firmware stays.
Talks to the wired keyboard over HID in wired mode.

## What we identified

- Wired board = `VID 320F / PID 5055`, manufacturer `Telink`
  (Evision platform — same family as Wobkey Rainy75 / GMK87 / FEKER Alice80).
- Wireless dongle = `VID 25A7 / PID FA7C` (`Compx`). NOT the target.
- Stock app = `C:\Program Files (x86)\Noir Gear\NoirTimeless82.exe`
  uses `hid.dll`: `HidD_SetOutputReport` + `WriteFile`. Chip `VS11K09A`,
  upgrader `UpgradKit-RK-X67-NB-831`.
- Target interface (no admin needed, verified):
  `MI_01 Col04`, usage `FF1C:0092`, `in=64 out=64 feat=0`.
  64-byte reports, Report ID `0x04`, checksum u16LE at `[1..2]` = sum of `[3..63]`,
  ACK = response with `resp[3] == cmd`.
- DO NOT TOUCH for LED work: `MI_02` usage `FFEF` (`in=64 out=64 feat=64`)
  — that is the OTA firmware channel (report ID `0x05`, `0xFF` padding).
  Wrong bytes there can brick the board.
- `MI_01 Col05` (`in=33 out=33`) looks like the VIA channel (32+1).
  RGB via VIA is read-only on this platform (writes ACK but ignored).

## References

- `gmk87-c-spec.md` protocol (same VID:PID, display CONFIG layout A/B,
  commands `01/06/21/02/23`, 48-byte config buffer).
- Rainy75-ZMK `docs/protocols.md` (OTA on FFEF — avoid) and
  `docs/wob-driver-analysis.md` (device table: `320F:5055 / FF1C:0092 / report 4`,
  packet-based protocol).
- Stock `DefaultData\default_light.json` mode IDs 0..30
  (custom=19, off=20, audiorecord=29, capturecolor=30).
- Stock profile `%LOCALAPPDATA%\NoirTimeless82\keyboard\*.Json`
  `LightInfo { Light, Red, Green, Blue, Speed, ... }`.

## Build (MinGW, zero extra deps — only system hid.dll + setupapi)

```
cd D:\Project\keyboard\timeless82
mingw32-make
.\timeless82.exe list
.\timeless82.exe caps
```

Memory: native C, no runtime. Idle 0 (CLI exits). Resident while
running < 3 MB. Python is not involved.

## Protocol findings (probed live, 2026-09-10)

- `FF1C:0092` report: `[0]=0x04 reportID, [1..2]=checksum u16LE over [3..63],
  [3]=cmd, [4]=len, [5..7]=pos LE, [8..63]=payload`.
- Reply echoes: `[1..2]=request checksum, [3]=cmd, [4]=len, [5..7]=pos`.
- Full 0x00..0xFF len-0 scan: everything ACK-echoes or status-FF,
  except `0x1A` which returns fixed `64 02` (len/pos ignored, static
  across 40 polls while LEDs cycled — treated as fixed info, not state).
- `MI_01 Col05` (33/33) rejects WriteFile — not a usable VIA channel.
  v1 has no VIA; FF1C is the only control channel.
- `FFEF`/MI_02 never opened for write (helper refuses).

## OLED findings

- Stock frames: `%LOCALAPPDATA%\NoirTimeless82\keyboard\ScreenFrame.json`,
  `{"Frame": [21 x 8192 bytes]}`. 8192 = 128x64, 1 byte/px, row-major
  (256-wide render duplicates => true width 128). 255 = lit.
  Slots 0-3 hold user animation, 4-20 empty.
- Upload trial: `oled FILE [NFRAMES=1] [DISP_IDX=1]` sends Evision display
  pipeline INIT,INIT,CONFIG,COMMIT,0x23,INIT,IMAGE(56B chunks),COMMIT
  with `cfg[33]=disp_idx, cfg[34]=nframes, cfg[39..40]=100ms`.
  `oled_test.bin` = top-white/bottom-black + border + diagonal.
- 2026-09-10: zeroed-CONFIG trial proved CONFIG+COMMIT applies; screen
  switched to image slot showing stored frame ("rocket").
  Bug fixed: overlapped WriteFile needs `ok=GetOverlappedResult(...)`
  (false write-fail); drain stale ACKs before each session.
- idx1 = user animation slot, idx2 = factory timeless logo.
  64B IMAGE streaming (gmk87-style) is ACKed but ignored; full 21-frame
  stream froze animation (0x23 = freeze confirmed). Pixel path differs.

## OLED pipeline (WORKING method, verified 2026-09-10)

- Format: 128x64, 1 byte/px grayscale, row-major, 255 = lit.
- Stock frames: `%LOCALAPPDATA%\NoirTimeless82\keyboard\ScreenFrame.json`
  `{"Frame": [21 x 8192]}`. Screen 5 (app numbering) plays slots 0-3.
- Direct CLI upload does NOT work: 64B IMAGE streams produce chaos;
  stock's 17B FF-framed SetOutputReport is refused (err=87) on every
  local handle. Cause parked.
- Working method: `py -3 setframes.py a.png [b.png c.png d.png]` writes
  art into slots 0-3 (auto-backup `ScreenFrame.json.bak`), then stock app
  screen Apply uploads with its own framing + lighting bytes.
  Same still x4 = static; 4 different frames = animation.
- LEDs/Fn are never touched by this path. CLI HID writes to the keyboard
  are parked per user request; `timeless82.exe oled` must not be used.

## OLED pixel path (from stock app disassembly)

- Stock app sends ONLY 17-byte `HidD_SetOutputReport` packets for pixels:
  `[FF][B1][B2][00][13 payload bytes]`, payload clamped to 0xF7.
- 12 sends per chunk, headers cycle:
  22AAx7B 22ADx6B 44AAx7B 44ADx6B 22ABx7B 22AEx6B
  44ABx7B 44AEx6B 22ACx7B 22AFx6B 44ACx7B 44AFx6B
  (func @0x48eee0, call sites 0x48f1ad..0x48f652).
- `oled2 FILE [OFF=0] [N=39]`: replicates S1+S2 (+more for larger N).
  64B report-4 path = lighting/display-select only.

## OLED frame upload (Frida-proven, no stock app)

- `oledN FILE NFRAMES [DISP_IDX=4] [INTERVAL=100]`: FILE = N concatenated
  1024B frames (N=1..128; 128 = verified hardware cap, higher wraps),
  column-major 1-bit MSB-top
  (byte[c*8+pg] bit 7-k = pixel (pg*8+k, c)). (`oled30` = alias.)
- Sequence: INIT(0x01), IMAGE(0x21, 56B chunks pos 0..N*1024-1),
  COMMIT(0x02), INIT, CONFIG(0x06 len 56), COMMIT. No 0x23.
- CONFIG = 56B zero except `[22]=0x03`, `[33]=disp_idx` (0-based screen:
  4 = screen 5 user anim), `[34]=N`, `[35..37]=BCD clock` sec/min/hour
  (capture `39 55 18` = 18:55:57), `[39..40]=frame interval u16 LE ms`
  (larger = slower; stock default 100).
- 2026-09-11: interval offset proven by Frida capture of the stock app's own
  CONFIG write (app set to 302ms -> `2E 01` at `[39..40]`, clock bytes
  matching the write timestamp exactly, checksum valid). The firmware
  IGNORES `[43..44]`, and it echoes the whole config buffer back verbatim,
  so reading our own bytes at our own offset made a dead knob look alive.
  The old "interval is clamped, frames are the only speed lever" note was a
  consequence of that bug, not of the firmware.
- Tools used to prove it (read-only, no writes to the device):
  `py -3 frida_hid.py [secs=120] [out]` attaches to the stock app and logs
  every HID write with a millisecond timestamp and the full 64-byte report
  (the stock app is `requireAdministrator`, so Frida needs UAC);
  `py -3 cfgwatch.py [out]` polls the device's stored CONFIG (`q 5 56 0`) and
  logs every change, needing no admin.

## OLED live now-playing (independent, no stock app)

- Pipeline: `nowplaying.exe [art_path]` (TSV `status\ttitle\tartist` /
  `NO-SESSION`; with a path, also dumps the raw SMTC thumbnail bytes there,
  deleting the file when the session has no cover art)
  -> `nowshow.py` (N x 128x64 PNGs `anim_np_0..N-1.png`; layout: top bar =
  drawn transport glyph left (play triangle / pause bars) + date right,
  scrolling **title** hero below the rule, **artist** static centered at
  the bottom (ellipsized). Idle = big clock + date card, re-uploaded once a
  minute; short/idle = STATIC_N=4 identical frames) -> pack -> `oledN`.
- **Panels.** `nowlive.py --mode np|sys|auto` picks what the screen shows
  (persisted in `tray.mode`, chosen from the tray **Screen** menu):
  - `np` — now playing, or the clock/date card when nothing plays.
  - `sys` — system monitor (`nowsys.py`): CPU + GPU bars, then
    `RAM n%`, temperature, battery, clock, network, disk rows. Values are
    live, so the panel re-uploads every `--syssec` seconds (default 5).
  - `auto` — `np` while a track plays, `sys` while idle.
  Missing counters render `--` (this machine exposes no Thermal Zone
  Information, so temperature is always `--`); nothing raises.
- **Album art.** When the session has a thumbnail, `nowart.py` decodes it,
  center-crops to a square (no stretch), autocontrasts and thresholds to
  1-bit, and `nowshow.render_track` lays it out as a 56x56 left column with
  a narrower scrolling title/artist column beside it. No thumbnail -> the
  full-width layout, unchanged.
- Frame count dynamic via `pick_plan` (computed on the **title** width):
  STATIC_N=4 when short/idle (step 0);
  else `--maxn` (default 64, hard cap MAXN=128) sets a frame budget, with the
  smallest integer STEP = ceil((tw+MIN_GAP)/maxn) -> N*STEP==L exact seam
  (frameN byte-identical frame0); stale PNGs >= N deleted. Upload time (and
  keyboard freeze) is ~65ms/frame, so maxn trades scroll speed vs freeze:
  long title -> 32 frames ~2.1s, 64 ~4.1s, 128 ~8.2s. Pace = STEP px per
  frame interval, and the interval is derived from `--speed PXPS` (default
  110), so `--maxn` trades smoothness (smaller STEP) against freeze time
  without changing how fast the text crosses the screen.
- JSON path (default, no HID): `nowlive.py` re-renders on track/state
  change (no per-minute refresh anymore), `setframes.py` writes N PNGs into
  slots 0..N-1 (grows the slot
  array up to 120 as needed). Direct path: `nowlive.py --direct` packs N
  frames -> `npN.bin` -> `oledN FILE NFRAMES`.
- Wire: 64B Layout-A `[0]=0x04 [1..2]=checksum u16LE sum[3..63] [3]=cmd
  [4]=len [5..7]=pos LE24 [8..63]=payload`; INIT(0x01), IMAGE(0x21, 56B
  chunks pos 0..N*1024-1), COMMIT(0x02), INIT, CONFIG(0x06 len 56), COMMIT.
  No 0x23. Frames = Nx1024B packed col-major MSB-top
  (`byte[c*8+pg]` bit `7-k` = pixel `(pg*8+k, c)`); CONFIG 56B zero except
  `[22]=0x03, [33]=disp_idx(4=screen 5), [34]=N, [35..37]=BCD clock,
  [39..40]=frame interval u16 LE ms`.
- Usage: `py -3 nowlive.py --direct [--once] [poll_sec=5]` (+ `--dry`
  render+pack only, `--speed PXPS` scroll pace default 110, `--interval MS`
  pins a fixed device frame interval instead, `--disp I` default 4, `--maxn N`
  frame budget 1..128 default 32, `--mode np|sys|auto` panel selection,
  `--syssec N` system-panel cadence in seconds 1..300 default 5).
  Pace = STEP px per frame interval, and the
  interval is derived as `round(STEP*1000/speed)`, so the frame budget trades
  smoothness against freeze time instead of changing the scroll speed.
  Measured on a 76-char YouTube title (title width 1120px, so L=1152):
  `--maxn 16` -> n=16 STEP=71 iv=645ms upload 1.9s; `--maxn 32` -> n=32
  STEP=36 iv=327ms 2.9s; `--maxn 128` -> n=125 STEP=9 iv=82ms 9.0s. All loop
  in ~10.2-10.5s, so fewer frames never scroll faster, only chunkier - and
  STEP is what a viewer notices, so long titles want a bigger `--maxn`.
  `nowshow.py` (dry render), `nowsys.py` (dry render of the sys panel) and
  `nowart.py` (x4 `art_preview.png` of the current `np_art.bin`) each render
  to PNGs for eyeballing with no hardware and no upload.
- JSON path caveat: there the stock app owns the rate, so `--maxn` does
  change the pace (speed = STEP px per the app's own FrameIntervalTime).
  Lower the frame budget there and raise the app's interval to match.
- Keyboard lock during upload: the board stalls its key scanning while it
  ingests IMAGE data (~65ms/frame; firmware-paced, and the per-chunk
  ACK wait is already optimal — fire-and-forget is *slower*, ~20s, because
  the device IN buffer backs up). Opening the handle alone does not freeze
  keys, and pausing between IMAGE reports does not help — the board holds
  its key matrix off for the whole session (INIT..COMMIT). So the loop does
  not fight it, it just uploads less and only at rest:
  (a) `--maxn` caps frames; (b) 2s debounce collapses rapid track-skipping
  into a single upload; (c) `--idle-ms` (default 1500; 0 disables) defers
  the direct upload until no keyboard/mouse input (the sys panel skips the
  debounce: its key is time-bucketed, so there is nothing to collapse).
  When a track changes
  while you are typing it prints `deferred (input Nms ago)` and uploads the
  moment you pause. `--once` uploads immediately.
- Diagnostic: `timeless82.exe hold [MODE=open|wo|rw|init] [MS]` opens the
  display handle (read-only / write-only / rw / +INIT) and idles, to prove
  what does and does not block the keyboard.
- Safety: wired `320F:5055` only, `FF1C:0092`; never `FFEF`/MI_02, never
  `0xBE FC`/`0xBE EE`.
- Check screen 5 (slots 0-3 animation); revert via stock app Apply.

### SMTC hang (media poll never returns)

`nowplaying.exe` calls `GlobalSystemMediaTransportControlsSessionManager.RequestAsync()`,
which activates the **Now Playing Session Manager Service**
(`NPSMSvc` / `npsm.dll`) through the per-user instance `NPSMSvc_<id>`
(e.g. `NPSMSvc_cdc43`, a `svchost -k LocalService -p`). If that broker wedges,
`RequestAsync` blocks forever in an out-of-process LPC reply and every poll
times out (`System` log shows SCM 7011: 90000 ms transaction timeout from
`NPSMSvc_<id>`).

Restart the broker (no admin needed; the isolated svchost hosts only this
service, and SCM demand-starts it again on the next call):

```powershell
$pid = (sc.exe queryex NPSMSvc_cdc43 | Select-String 'PID').ToString().Split(':')[1].Trim()
taskkill /F /PID $pid
```

`Program.cs` also caps the whole call at 4 s and prints `NO-SESSION` on timeout
(plus per-stage timing on stderr), so a wedge can never stall `nowlive.py`.

## Launch at login + tray on/off menu (tray.ps1)

WinForms `NotifyIcon` (no new deps, no admin, no build). Tray menu:

- **Screen** — sub-items **Now playing**, **System monitor**, **Auto**; the
  choice is written to `tray.mode` and nowlive is restarted with it (there is
  no live-reload channel). Exactly one is checked, from the file, so an
  outside `-Action mode` flips the checkmark back.
- **Enabled** — starts/stops `py -3 nowlive.py` (child tree killed with
  `taskkill /T`; pid tracked in `nowlive.pid`). Output -> `nowlive.log`
  (+ `nowlive.err.log`).
- **Start with Windows** — creates/removes
  `%APPDATA%\...\Startup\timeless82-tray.lnk` (hidden PowerShell, window
  style 7).
- **Open log**, **Exit** (stops nowlive first).

**Icon.** Drawn in-process (no image files): rounded keycap + the Segoe Fluent
Icons keyboard glyph (`U+E765`, falls back to Segoe MDL2 Assets, then to three
drawn key rows), generated natively at 16/20/24/32/48/64 and packed into a
multi-size 32bpp ICO. Blue keycap while nowlive runs, grey while it is off, so
the tray shows state at a glance. `-IconPath foo.ico` (or a .png/.jpg) replaces
it; `-Action icon` writes `tray-icon-on.ico` / `tray-icon-off.ico` next to the
script plus a pixel census, for eyeballing the art outside a running tray.

**Disabling without uninstalling.** Two independent switches, both in the
tray menu:

| Want | Do |
|---|---|
| Stop the OLED loop now, keep the tray icon | uncheck **Enabled** |
| Stop it now *and* after every reboot (keep the tray icon) | uncheck **Enabled** (the choice is written to `tray.state`) |
| No tray icon either, permanently | **Exit**, then uncheck **Start with Windows** (or `-Action uninstall`) |
| Everything gone | `-Action disable` then `-Action uninstall` |

`tray.state` (`1`/`0`) is the source of truth, not the window: the tray
re-reads it every 2 s, so a running tray follows an outside `-Action
disable`, a crash cannot silently disable the loop (it restarts nowlive,
with a 15 s retry gap so a broken interpreter cannot spin), and `-Action
start` from a shell flips the menu checkmark back. Double-launch is blocked
by a `Local\timeless82-tray` mutex. Default child args are `--direct --mode
<selected>` (change with `-NowLiveArgs`, e.g. `'--maxn 32'` or `--dry`); the
mode is always appended from `tray.mode`, which is the source of truth for
the panel the same way `tray.state` is for on/off.

Headless control (same code path as the menu, for scripts/tests):

```
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action install    # add Startup shortcut
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action start [-NowLiveArgs '--direct --maxn 32']
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action enable     # desired=on  (starts nowlive)
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action disable    # desired=off (stops nowlive, survives reboot)
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action stop       # alias for disable
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action mode -Mode np|sys|auto   # panel choice (restarts nowlive)
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action status     # enabled=<desired> live=<running> autostart=<bool> mode=<m>
powershell -NoProfile -ExecutionPolicy Bypass -File tray.ps1 -Action uninstall
```

Running `tray.ps1` with no `-Action` (what the shortcut does) installs the
shortcut if missing, then obeys `tray.state`: it starts nowlive only if the
preference is on, and shows the icon either way.

## Safety rules

1. Wired mode only (`320F:5055` present). Never send anything to `FFEF`/MI_02.
2. Never send `0xBE 0xFC` (DFU), `0xBE 0xEE` (factory reset) on any interface.
3. `list` / `caps` perform zero HID writes (GENERIC_READ open + caps query).
4. Lighting writes come later, only on `FF1C:0092`, one mode at a time,
   verified by eye, stock profile re-applied to restore.
5. USBPcap sniffing needs admin (we run Medium integrity) — skipped.
   Active probing on the LED channel needs no admin.

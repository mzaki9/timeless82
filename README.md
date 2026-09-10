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
  with `cfg[33]=disp_idx, cfg[34]=nframes, cfg[43]=100ms`.
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

## OLED 30-frame upload (Frida-proven, no stock app)

- `oledN FILE NFRAMES [DISP_IDX=4] [INTERVAL=57]`: FILE = N concatenated
  1024B frames (N=1..30), column-major 1-bit MSB-top
  (byte[c*8+pg] bit 7-k = pixel (pg*8+k, c)). (`oled30` = alias.)
- Sequence: INIT(0x01), IMAGE(0x21, 56B chunks pos 0..N*1024-1),
  COMMIT(0x02), INIT, CONFIG(0x06 len 56), COMMIT. No 0x23.
- CONFIG = 56B, all zero except payload[22]=0x03, payload[33]=disp_idx
  (abs41, 0-based screen: 4 = screen 5 user anim), payload[34]=N (abs42),
  payload[35]=interval (abs43, stock 57; larger = slower),
  payload[36..37]=55 18 (abs44..45).

## OLED live now-playing (independent, no stock app)

- Pipeline: `nowplaying.exe` (TSV `status\ttitle\tartist` / `NO-SESSION`)
  -> `nowshow.py` (N x 128x64 PNGs `anim_np_0..N-1.png`: status+clock /
  scrolling "Title - Artist" / date; idle/short = STATIC_N=4 identical
  frames) -> pack -> `oledN`.
- Frame count dynamic via `pick_plan`: STATIC_N=4 when short/idle (step 0),
  else smallest smooth STEP in 3/4/5/6/8 whose N fits 30, else N=30 fast
  fallback with bigger STEP. N*STEP==L exact seam (frameN byte-identical
  frame0); stale PNGs >= N deleted.
- JSON path (default, no HID): `nowlive.py` re-renders on track/state
  change, `setframes.py` writes N PNGs into slots 0..N-1 (30 slots kept).
  Direct path: `nowlive.py --direct` packs N frames -> `npN.bin` ->
  `oledN FILE NFRAMES`.
- Wire: 64B Layout-A `[0]=0x04 [1..2]=checksum u16LE sum[3..63] [3]=cmd
  [4]=len [5..7]=pos LE24 [8..63]=payload`; INIT(0x01), IMAGE(0x21, 56B
  chunks pos 0..N*1024-1), COMMIT(0x02), INIT, CONFIG(0x06 len 56), COMMIT.
  No 0x23. Frames = Nx1024B packed col-major MSB-top
  (`byte[c*8+pg]` bit `7-k` = pixel `(pg*8+k, c)`); CONFIG 56B zero except
  `payload[22]=0x03, payload[33]=disp_idx(4=screen 5), payload[34]=N,
  payload[35]=interval, payload[36..37]=55 18`.
- Usage: `py -3 nowlive.py --direct [--once] [poll_sec=5]` (+ `--dry`
  render+pack only, `--interval MS` frame time default 120, `--disp I`
  default 4); e.g. slower: `--interval 180`; faster: `--interval 80`.
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

## Safety rules

1. Wired mode only (`320F:5055` present). Never send anything to `FFEF`/MI_02.
2. Never send `0xBE 0xFC` (DFU), `0xBE 0xEE` (factory reset) on any interface.
3. `list` / `caps` perform zero HID writes (GENERIC_READ open + caps query).
4. Lighting writes come later, only on `FF1C:0092`, one mode at a time,
   verified by eye, stock profile re-applied to restore.
5. USBPcap sniffing needs admin (we run Medium integrity) — skipped.
   Active probing on the LED channel needs no admin.

#!/usr/bin/env python3
"""Capture HID traffic from the stock NoirTimeless82.exe with frida.

Answers "does the app push frames, and how often?": every HidD_SetOutputReport /
HidD_SetFeature / WriteFile (17/33/64/65-byte HID-shaped writes) is logged with
a millisecond timestamp and the first 32 bytes of the report, so a per-second
push rate and the CONFIG interval bytes can be read straight off the log.

Usage: py -3 frida_hid.py [seconds=120] [out=frida_hid.log]
Read-only: attaches to the already-running stock app, sends nothing to the
device, never touches FFEF/OTA.
"""
import datetime
import sys
import time

import frida

SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 120
OUT = sys.argv[2] if len(sys.argv) > 2 else r"D:\Project\keyboard\timeless82\frida_hid.log"

SRC = r"""
function hexs(ptr, n) {
  const b = new Uint8Array(ptr.readByteArray(n));
  return Array.from(b).map(x => x.toString(16).padStart(2, '0')).join(' ');
}
let t0 = Date.now();
function log(api, len, ptr) {
  // full 64-byte report: CONFIG payload starts at report [8], so the frame
  // interval cfg[39..40] sits at report byte 47/48 and needs the whole report.
  send({ t: Date.now() - t0, api: api, len: len, d: hexs(ptr, Math.min(len, 64)) });
}
const hid = Process.getModuleByName('hid.dll');
const k32 = Process.getModuleByName('kernel32.dll');
['HidD_SetOutputReport', 'HidD_SetFeature'].forEach(function (fn) {
  const a = hid.getExportByName(fn);
  if (a) Interceptor.attach(a, {
    onEnter(args) {
      const len = args[2].toInt32();
      if (len >= 8 && len <= 128) log(fn, len, args[1]);
    }
  });
});
Interceptor.attach(k32.getExportByName('WriteFile'), {
  onEnter(args) {
    const len = args[2].toInt32();
    // HID report sizes only; ignores the app's ordinary file/pipe IO.
    if (len === 17 || len === 33 || len === 64 || len === 65) log('WriteFile', len, args[1]);
  }
});
send({ ready: true });
"""


def main():
    f = open(OUT, "w", encoding="utf-8", buffering=1)
    t0 = time.time()
    n = 0

    def on_message(msg, data):
        nonlocal n
        if msg["type"] != "send":
            f.write(f"# {msg}\n")
            return
        p = msg["payload"]
        if p.get("ready"):
            f.write(f"# attached, capturing {SECS}s\n")
            return
        n += 1
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        f.write(f"{p['t']:>8} {ts} {p['api']:<20} len={p['len']:<3} {p['d']}\n")

    try:
        sess = frida.attach("NoirTimeless82.exe")
    except frida.ProcessNotFoundError:
        print("stock app not running — start NoirTimeless82.exe first")
        return 1
    script = sess.create_script(SRC)
    script.on("message", on_message)
    script.load()
    print(f"attached to NoirTimeless82.exe, logging {SECS}s -> {OUT}", flush=True)
    while time.time() - t0 < SECS:
        time.sleep(0.5)
    script.unload()
    sess.detach()
    f.close()
    print(f"done: {n} HID calls captured")
    return 0


if __name__ == "__main__":
    sys.exit(main())

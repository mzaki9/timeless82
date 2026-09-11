#!/usr/bin/env python3
"""Log the device's stored CONFIG whenever it changes. Zero-admin, read-only.

The firmware echoes the config it last stored (cmd 0x05, 56 bytes), so a
setting change made in the stock app shows up here as a byte diff even though
we can never see the app's own HID writes (it runs elevated).

Fields: [22]=0x03 magic [33]=disp idx [34]=nframes [35..37]=BCD clock
sec,min,hour [39..40]=frame interval u16 LE ms (the stock app's own offset).

Usage: py -3 cfgwatch.py [out=cfgwatch.log]
"""
import datetime
import re
import subprocess
import sys
import time

HERE = r"D:\Project\keyboard\timeless82"
EXE = HERE + r"\timeless82.exe"
OUT = sys.argv[1] if len(sys.argv) > 1 else HERE + r"\cfgwatch.log"
POLL = 0.4


def read():
    try:
        r = subprocess.run([EXE, "q", "5", "56", "0"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    body = r.stdout.split("bytes:", 1)[1] if "bytes:" in r.stdout else ""
    lines = re.findall(r"^(?:[0-9A-Fa-f]{2} ?)+$", body, re.M)
    b = bytes(int(x, 16) for line in lines for x in line.split())
    return b[8:] if len(b) >= 64 else None


def fmt(p):
    return (f"disp={p[33]} n={p[34]} interval={p[39] | (p[40] << 8)} "
            f"clock={p[37]:02X}:{p[36]:02X}:{p[35]:02X}")


def main():
    f = open(OUT, "a", encoding="utf-8", buffering=1)
    f.write(f"# cfgwatch start {datetime.datetime.now():%H:%M:%S} poll={POLL}s\n")
    print(f"logging CONFIG changes -> {OUT}", flush=True)
    last = None
    while True:
        p = read()
        # While an upload is in flight the IN pipe still holds report ACKs, so
        # a read can come back as image residue; the 0x03 magic at [22] is what
        # marks a sample as a real config echo.
        if p is not None and p[22] != 0x03:
            p = None
        if p is not None and p != last:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if last is None:
                f.write(f"{ts} INITIAL  {fmt(p)}\n")
            else:
                diff = [f"[{i}]{last[i]:02X}>{p[i]:02X}" for i in range(56) if p[i] != last[i]]
                f.write(f"{ts} CHANGE   {fmt(p)}\n")
                f.write(f"{'':>12} {' '.join(diff)}\n")
            f.write(f"{'':>12} raw={' '.join(f'{v:02X}' for v in p)}\n")
            last = p
        time.sleep(POLL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

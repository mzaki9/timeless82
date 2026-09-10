#!/usr/bin/env python3
"""Spawn stock app under Frida HID hook; log to hidfrida.log until app exits.

Usage: py -3 frida_run.py   (stock GUI appears; user clicks screen Apply,
then CLOSES the app; log is written on exit)
"""
import sys
import time

import frida

EXE = r"C:\Program Files (x86)\Noir Gear\NoirTimeless82.exe"
LOG = r"D:\Project\keyboard\timeless82\hidfrida.log"
JS = r"D:\Project\keyboard\timeless82\frida_hook.js"

msgs = []
LOGFH = None


def on_msg(m, data):
    import time as _t
    ts = _t.strftime("%H:%M:%S")
    if m["type"] == "send":
        p = m["payload"]
        line = p.get("t", "?")
        if line == "open":
            s = f"OPEN {p['h']} {p['path']}"
        elif line in ("SOR", "SFeat", "WF"):
            hx = bytes(data).hex(" ") if data else ""
            s = f"{line} h={p['h']} len={p['len']} ok={p['ok']} {hx}"
        elif line in ("IO", "NTIO"):
            hx = bytes(data).hex(" ") if data else ""
            s = (f"{line} h={p['h']} code=0x{p['code']:08X} len={p['len']} "
                 f"ok={p['ok']} {hx}")
        elif line == "MSGBOX":
            s = f"MSGBOX [{p.get('cap','')}] {p.get('txt','')}"
        elif line == "PROC":
            s = f"PROC ok={p.get('ok')} app={p.get('app','')} cmd={p.get('cmd','')}"
        else:
            s = str(p)
        msgs.append(s)
        if LOGFH is not None:  # incremental: survives kills
            LOGFH.write(f"{ts} {s}\n")
            LOGFH.flush()
        if len(msgs) <= 30 or line in ("SOR", "SFeat", "WF", "MSGBOX", "PROC"):
            print("EVT", s, flush=True)


def proc_alive(pid):
    import ctypes
    SYNCHRONIZE = 0x00100000
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return False
    rc = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
    ctypes.windll.kernel32.CloseHandle(h)
    return rc != 0  # 0 = signalled = exited


def find_stock_pid():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NoirTimeless82.exe",
                          "/FO", "CSV", "/NH"], capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "noirtimeless82.exe":
            try:
                return int(parts[1])
            except ValueError:
                pass
    return None


def main():
    global LOGFH
    import os
    import subprocess
    os.chdir(os.path.dirname(EXE))  # stock app needs its own dir (Skin/DefaultData)
    dev = frida.get_local_device()
    if len(sys.argv) >= 2 and sys.argv[1] == "attach":
        pid = find_stock_pid()
        if pid is None:
            print("stock app not running; launch it first, then rerun",
                  flush=True)
            return 2
        print(f"attaching to {pid}; click screen Apply, then CLOSE the app",
              flush=True)
        sess = dev.attach(pid)
    else:
        pid = dev.spawn([EXE])
        print(f"spawned {pid}; waiting for process init...", flush=True)
        dev.resume(pid)
        time.sleep(4)  # let exe/kernel32/hid.dll map before attaching
        sess = dev.attach(pid)
        print("attached; click screen Apply in stock app, then CLOSE it",
              flush=True)
    with open(JS, encoding="utf-8") as f:
        script = sess.create_script(f.read())
    script.on("message", on_msg)
    script.load()
    LOGFH = open(LOG, "w", encoding="utf-8")
    print("hooked; click screen Apply in stock app, then CLOSE it",
          flush=True)
    while proc_alive(pid):
        time.sleep(2)
    time.sleep(1)
    if LOGFH is not None:
        LOGFH.close()
    print(f"app exited; {len(msgs)} events -> {LOG}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

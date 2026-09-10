#!/usr/bin/env python3
"""Self-test: hook a benign target to validate Frida mechanism."""
import sys
import time

import frida

TARGET = sys.argv[1] if len(sys.argv) > 1 else r"C:\Windows\System32\notepad.exe"
JS = r"D:\Project\keyboard\timeless82\frida_t.js"


def on_msg(m, d):
    print("EVT", m.get("payload", m), flush=True)


dev = frida.get_local_device()
pid = dev.spawn([TARGET])
print("spawned", pid, flush=True)
sess = dev.attach(pid)
with open(JS, encoding="utf-8") as f:
    sess.create_script(f.read()).load() if False else None
    script = sess.create_script(open(JS, encoding="utf-8").read())
script.on("message", on_msg)
script.load()
dev.resume(pid)
time.sleep(6)
try:
    dev.kill(pid)
except Exception as e:
    print("kill:", e, flush=True)
print("done", flush=True)

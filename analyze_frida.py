#!/usr/bin/env python3
"""Analyze hidfrida.log WF burst: group by gap, dump headers."""
import sys
path = sys.argv[1] if len(sys.argv) > 1 else "hidfrida.log"
lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
wf = [l for l in lines if len(l.split()) > 1 and l.split()[1] == "WF"]
print("WF total:", len(wf))
pkts = []
for l in wf:
    parts = l.split()
    ts = parts[0]
    h = parts[2].split("=")[1]
    hx = l.split("ok=")[1].split(None, 1)[1].strip().split()
    pkts.append((ts, h, hx))
for i, (ts, h, hx) in enumerate(pkts):
    head = " ".join(hx[:10])
    print("%3d %s %s len=%d | %s" % (i, ts, h, len(hx), head))
# header nibble analysis: bytes 1..3
print("--- distinct b1 values ---")
from collections import Counter
c = Counter(tuple(p[2][:6]) for p in pkts)
print("distinct 6B prefixes:", len(c))
# burst split: same timestamp = burst? show time groups
print("--- time groups ---")
cg = Counter(p[0] for p in pkts)
for k in sorted(cg):
    print(k, cg[k])
# check olED 17B? our pkts are 64B WF with 04 report id
print("--- lengths ---")
print(Counter(len(p[2]) for p in pkts))
print("--- handles ---")
print(Counter(p[1] for p in pkts))
# dump full bytes of first burst control packets (non-21 38 pattern)
print("--- non-payload control packets (b1,b2 not XX XX 21 38) ---")
for i, (ts, h, hx) in enumerate(pkts):
    if not (hx[2] == "21" and hx[3] == "38") and not (hx[2] == "02" and hx[3] == "38"):
        print(i, ts, " ".join(hx))

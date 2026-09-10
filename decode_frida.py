#!/usr/bin/env python3
"""Deep decode of hidfrida.log WF bursts."""
import sys
path = sys.argv[1] if len(sys.argv) > 1 else "hidfrida.log"
lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
wf = [l for l in lines if len(l.split()) > 1 and l.split()[1] == "WF"]

def parse(l):
    ts = l.split()[0]
    hx = l.split("ok=")[1].split(None, 1)[1].strip().split()
    return ts, bytes(int(x, 16) for x in hx)

pkts = [parse(l) for l in wf]
out = []
out.append("total WF=%d" % len(pkts))
# checksum verify
bad = 0
for i, (ts, b) in enumerate(pkts):
    cs = sum(b[3:]) & 0xFFFF
    got = b[1] | (b[2] << 8)
    if cs != got:
        bad += 1
        out.append("BADCS idx=%d cs=%04X got=%04X" % (i, cs, got))
out.append("bad checksum count=%d" % bad)
# structure
out.append("idx ts cmd len pos payload_first8")
for i, (ts, b) in enumerate(pkts):
    cmd, ln = b[3], b[4]
    pos = b[5] | (b[6] << 8) | (b[7] << 16)
    out.append("%d %s %02X %02X pos=%d Fe=%s" % (i, ts, cmd, ln, pos, b[8:16].hex(" ")))
# IMAGE stream contiguity: cmd==0x21 and len==0x38
out.append("--- IMAGE runs (cmd 21 len 38) ---")
run = []
for i, (ts, b) in enumerate(pkts):
    if b[3] == 0x21 and b[4] == 0x38:
        run.append((i, b[5] | (b[6] << 8) | (b[7] << 16)))
    else:
        if run:
            poss = [p for _, p in run]
            ok = all(q - p == 56 for p, q in zip(poss, poss[1:]))
            out.append("run idx %d..%d n=%d pos %d..%d step56=%s total=%dB" %
                       (run[0][0], run[-1][0], len(run), poss[0], poss[-1], ok, len(run) * 56))
            run = []
if run:
    poss = [p for _, p in run]
    ok = all(q - p == 56 for p, q in zip(poss, poss[1:]))
    out.append("run idx %d..%d n=%d pos %d..%d step56=%s total=%dB" %
               (run[0][0], run[-1][0], len(run), poss[0], poss[-1], ok, len(run) * 56))
open("apply_analysis.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out[:40]))
print("... full -> apply_analysis.txt")

#!/usr/bin/env python3
"""Parse USBPcap captures for 320F:5055 HID traffic.

Usage: parse_cap.py cap.pcap [--dev BUS,DEV]

Lists devices (via GET_DESCRIPTOR), then dumps host-to-device SET_REPORT
control transfers for the keyboard in chronological order.
"""
import struct
import sys
from collections import Counter

# URB_FUNCTION_* (low 16 bits as stored by USBPcap)
F_CONTROL = 0x0008
F_BULK = 0x0009
F_INTERRUPT = 0x000A


def packets(path):
    d = open(path, "rb").read()
    magic, _, _, _, _, _, dlt = struct.unpack("<IHHIIII", d[:24])
    assert magic == 0xA1B2C3D4 and dlt == 249, "not a USBPcap file"
    off = 24
    while off + 16 <= len(d):
        _, _, cl, _ = struct.unpack("<IIII", d[off:off + 16])
        off += 16
        p = d[off:off + cl]
        off += cl
        if len(p) < 27:
            continue
        hlen, irp, status, func, info, bus, dev, ep, xfer, dlen = \
            struct.unpack("<HQIHBHHBBI", p[:27])
        yield bus, dev, ep, xfer, func, p[27:27 + dlen]


def main(argv):
    pkts = list(packets(argv[1]))
    print("packets:", len(pkts))
    # 1. inventory devices
    devices = {}
    for bus, dev, ep, xfer, func, data in pkts:
        if func == F_CONTROL and len(data) >= 18 and data[0] == 0x80 \
                and data[1] == 0x06 and data[2] == 0x00 and data[3] == 0x01:
            vid, pid = struct.unpack("<HH", data[8 + 8:8 + 12])
            devices[(bus, dev)] = (vid, pid)
    for k, v in sorted(devices.items()):
        print(f"dev bus={k[0]} addr={k[1]}: {v[0]:04X}:{v[1]:04X}")
    # 2. keyboard SET_REPORTs
    kb = [k for k, v in devices.items() if v == (0x320F, 0x5055)]
    if len(argv) > 3 and argv[2] == "--dev":
        b, a = argv[3].split(",")
        kb = [(int(b), int(a))]
    if not kb:
        print("keyboard not found in descriptors; use --dev BUS,DEV")
        return 1
    print("keyboard at:", kb)
    n = 0
    for i, (bus, dev, ep, xfer, func, data) in enumerate(pkts):
        if (bus, dev) not in kb or func != F_CONTROL or len(data) < 8:
            continue
        bm, br = data[0], data[1]
        wv, wi, wl = struct.unpack("<HHH", data[2:8])
        if bm == 0x21 and br == 0x09:  # SET_REPORT
            payload = data[8:]
            print(f"[{i}] SET_REPORT type={wv >> 8} id={wv & 0xFF} "
                  f"idx={wi} len={len(payload)} : {payload[:16].hex(' ')}")
            n += 1
            if n > 400:
                print("... truncated at 400"); break
    print("total SET_REPORT:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

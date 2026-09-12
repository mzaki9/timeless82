#!/usr/bin/env python3
"""System monitor panel: CPU/GPU bars + RAM/temp/battery + clock/net/disk rows.

Stdlib only (ctypes): PDH performance counters for CPU/GPU/net/disk, plus
kernel32 GlobalMemoryStatusEx (RAM) and GetSystemPowerStatus (battery).
No pip deps, no admin.

A counter that this machine does not expose (e.g. Thermal Zone Information on
many desktops) is simply absent: its field renders as "--". Pdh raises only
when the query itself cannot be opened or no counter at all could be added.

Usage: nowsys.py -> anim_sys_0.png (dry render for eyeballing).
nowlive.py imports sample()/render() and uploads via `timeless82.exe oledN`.
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime

import nowshow

STATIC_N = 4
SMALL = 10  # font px for the two value rows
HEAD = 10  # font px for the CPU/GPU header labels

CPU_COUNTER = r"\Processor Information(_Total)\% Processor Time"
GPU_COUNTER = r"\GPU Engine(*engtype_3D)\Utilization Percentage"
NET_COUNTER = r"\Network Interface(*)\Bytes Received/sec"
DISK_COUNTER = r"\PhysicalDisk(_Total)\% Idle Time"
TEMP_COUNTER = r"\Thermal Zone Information(*)\High Precision Temperature"

PATHS = (CPU_COUNTER, GPU_COUNTER, NET_COUNTER, DISK_COUNTER, TEMP_COUNTER)

PDH_FMT_DOUBLE = 0x00000200
GPU_PHYS = "_phys_0_"
RATE_SETTLE = 0.3  # s between the two collects a PDH rate counter needs


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR),
                ("FmtValue", PDH_FMT_COUNTERVALUE)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", wintypes.BYTE),
                ("BatteryFlag", wintypes.BYTE),
                ("BatteryLifePercent", wintypes.BYTE),
                ("SystemStatusFlag", wintypes.BYTE),
                ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def _kernel32():
    return ctypes.WinDLL("kernel32")


class Pdh:
    """One PDH query holding all monitored counters.

    Primes with two collects 0.3s apart (rate counters need a delta), then
    read() does a single collect + array read per counter.
    """

    def __init__(self, paths=PATHS):
        self._pdh = ctypes.WinDLL("pdh")
        self._q = wintypes.HANDLE()
        self._counters = {}
        for fn, args in (
            ("PdhOpenQueryW", [wintypes.LPCWSTR, ctypes.c_size_t,
                               ctypes.POINTER(wintypes.HANDLE)]),
            ("PdhAddEnglishCounterW", [wintypes.HANDLE, wintypes.LPCWSTR,
                                       ctypes.c_size_t,
                                       ctypes.POINTER(wintypes.HANDLE)]),
            ("PdhCollectQueryData", [wintypes.HANDLE]),
            ("PdhGetFormattedCounterArrayW",
             [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
              ctypes.POINTER(wintypes.DWORD),
              ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W)]),
            ("PdhRemoveCounter", [wintypes.HANDLE]),
            ("PdhCloseQuery", [wintypes.HANDLE]),
        ):
            f = getattr(self._pdh, fn)
            f.argtypes = args
            f.restype = ctypes.c_uint32
        if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._q)) != 0:
            self._q = None
            raise RuntimeError("PdhOpenQuery failed")
        try:
            for p in paths:
                c = wintypes.HANDLE()
                if self._pdh.PdhAddEnglishCounterW(
                        self._q, p, 0, ctypes.byref(c)) == 0:
                    self._counters[p] = c
            if not self._counters:
                raise RuntimeError("no PDH counter available")
            # Rate counters need two samples before they produce a value.
            # Collect now and settle; the caller's first read() is the second
            # collect. Priming with an extra read() here would make that first
            # caller read span ~0ms and return PDH_INVALID_DATA (CPU/disk/net
            # then render as "--" on the very first tick).
            self._pdh.PdhCollectQueryData(self._q)
            time.sleep(RATE_SETTLE)
        except Exception:
            self.close()
            raise

    def read(self):
        """path -> {instance: value}; {} for a counter that has no data."""
        if not self._q or self._pdh.PdhCollectQueryData(self._q) != 0:
            return {}
        return {p: self._read_array(c) for p, c in self._counters.items()}

    def _read_array(self, counter):
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        self._pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
            None)
        # The sizing call reports PDH_MORE_DATA when the array is present,
        # but some counters (e.g. Processor Information on Win11) return a
        # nonzero status with a valid size anyway: trust the size, not the rc.
        if not size.value:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        rc = self._pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
            ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W)))
        if rc != 0:
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
        out = {}
        for i in range(count.value):
            it = items[i]
            if it.FmtValue.CStatus == 0 and it.szName:
                out[it.szName] = it.FmtValue.doubleValue
        return out

    def close(self):
        if not self._q:
            self._counters.clear()
            return
        for c in self._counters.values():
            self._pdh.PdhRemoveCounter(c)
        self._counters.clear()
        self._pdh.PdhCloseQuery(self._q)
        self._q = None


def _first(vals):
    return next(iter(vals.values())) if vals else None


def _max_where(vals, pred):
    hit = [v for k, v in vals.items() if pred(k)]
    return max(hit) if hit else None


def sample(pdh=None):
    """One system snapshot. Missing counters become None (never raises)."""
    if pdh is None:  # one-shot caller (nowsys.py CLI, --dry): own + close
        pdh = Pdh()
        try:
            return sample(pdh)
        finally:
            pdh.close()
    vals = pdh.read()
    cpu = _first(vals.get(CPU_COUNTER, {}))
    gpu = _max_where(vals.get(GPU_COUNTER, {}),
                     lambda n: "engtype_3D" in n and GPU_PHYS in n)
    net = vals.get(NET_COUNTER, {})
    net_kbps = sum(net.values()) / 1024.0 if net else None
    disk_idle = _first(vals.get(DISK_COUNTER, {}))
    disk_pct = None if disk_idle is None else max(0.0, 100.0 - disk_idle)
    tenths_k = _max_where(vals.get(TEMP_COUNTER, {}), lambda n: True)
    temp_c = None if tenths_k is None else tenths_k / 10.0 - 273.15

    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(ms)
    k32 = _kernel32()
    total = avail = 0
    if k32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        total, avail = ms.ullTotalPhys, ms.ullAvailPhys
    ram_pct = (1.0 - avail / total) * 100.0 if total else 0.0

    sps = SYSTEM_POWER_STATUS()
    batt_pct = batt_ac = None
    if k32.GetSystemPowerStatus(ctypes.byref(sps)):
        batt_ac = sps.ACLineStatus == 1
        if sps.BatteryLifePercent != 255:
            batt_pct = int(sps.BatteryLifePercent)

    return {"cpu": cpu, "gpu": gpu, "ram_pct": ram_pct,
            "ram_used_gb": (total - avail) / 2**30,
            "ram_total_gb": total / 2**30,
            "temp_c": temp_c, "net_kbps": net_kbps, "disk_pct": disk_pct,
            "batt_pct": batt_pct, "batt_ac": batt_ac,
            "hhmm": datetime.now().strftime("%H:%M")}


def _pct(v):
    return "--" if v is None else f"{v:.0f}%"


def _kb(v):
    if v is None:
        return "--"
    return f"{v:.0f}K" if v < 1000 else f"{v / 1024:.1f}M"


def rows(stats):
    """(header-left, header-right, row3, row4) text, "--" for absent values."""
    head_l = f"CPU {_pct(stats['cpu'])}"
    head_r = f"GPU {_pct(stats['gpu'])}"
    row3 = f"RAM {_pct(stats['ram_pct'])}"
    temp = stats["temp_c"]
    row3 += f" {temp:.0f}C" if temp is not None else " --"
    if stats["batt_pct"] is not None:
        row3 += f" BATT {stats['batt_pct']}%"
    row4 = f"{stats['hhmm']} NET {_kb(stats['net_kbps'])} " \
           f"DSK {_pct(stats['disk_pct'])}"
    return head_l, head_r, row3, row4


def _row_font(d, *strings, maxw=122):
    """Largest of the small sizes that fits every string; rows never clip."""
    for sz in (SMALL, 9, 8):
        f = nowshow.font(sz)
        if all(nowshow.textw(d, s, f) <= maxw for s in strings):
            return f
    return nowshow.font(8)


def _bar(d, y, frac):
    d.rectangle([3, y, 124, y + 10], outline=255)
    w = int(118 * (0.0 if frac < 0 else 1.0 if frac > 1 else frac))
    if w:
        d.rectangle([5, y + 2, 5 + w, y + 8], fill=255)


def render(stats):
    """4 identical frames + meta. Never raises on missing values."""
    head_l, head_r, row3, row4 = rows(stats)
    im, d = nowshow.new()
    d.text((3, 0), head_l, font=nowshow.font(HEAD), fill=255)
    d.text((67, 0), head_r, font=nowshow.font(HEAD), fill=255)
    _bar(d, 15, (stats["cpu"] or 0.0) / 100.0)
    _bar(d, 29, (stats["gpu"] or 0.0) / 100.0)
    fr = _row_font(d, row3, row4)
    d.text((3, 41), row3, font=fr, fill=255)
    d.text((3, 53), row4, font=fr, fill=255)
    frames = [im.copy() for _ in range(STATIC_N)]
    return frames, {"what": "sys", "n": STATIC_N, "step": 0, "gap": 0}


def main():
    import glob

    t0 = time.time()
    try:
        pdh = Pdh()
    except Exception as e:
        print(f"pdh unavailable: {e}")
        return 1
    try:
        stats = sample(pdh)
        frames, meta = render(stats)
    finally:
        pdh.close()
    for i, im in enumerate(frames):
        im.point(lambda v: 255 if v >= 128 else 0).save(f"anim_sys_{i}.png")
    for stale in glob.glob("anim_sys_*.png"):
        try:
            idx = int(stale[len("anim_sys_"):-len(".png")])
        except ValueError:
            continue
        if idx >= meta["n"]:
            os.remove(stale)
    print(f"wrote anim_sys_0.png frames={meta['n']}")
    for k in ("cpu", "gpu", "ram_pct", "ram_used_gb", "ram_total_gb", "temp_c",
              "net_kbps", "disk_pct", "batt_pct", "batt_ac", "hhmm"):
        print(f"  {k}={stats[k]!r}")
    print(f"  rows={rows(stats)}")
    print(f"render_time={time.time() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

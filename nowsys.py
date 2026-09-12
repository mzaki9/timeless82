#!/usr/bin/env python3
"""System monitor panel: CPU / GPU / RAM bars, each labelled with its value,
plus the GPU temperature on the RAM line.

Two sources, both stdlib:
  * PDH performance counters (ctypes `pdh.dll`) for CPU %, GPU %.
  * NVML (`nvml.dll`, the same source `nvidia-smi` reads) for GPU temp.

Temperature is GPU-only *because this board has no CPU thermal sensor at
all*: PDH `\\Thermal Zone Information(*)` enumerates 0 instances,
`MSAcpi_ThermalZoneTemperature` returns "Not supported" and
`Win32_TemperatureProbe` reports an empty reading. Anything claiming a CPU
temp here would be inventing one, so the panel prints `TEMP --` when NVML
is unavailable and never fakes the other.

Everything degrades: a counter that is absent renders `--`, a missing GPU
renders no temperature, and `render` never raises.
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

import nowshow

STATIC_N = 4
SMALL = 10  # font px for the three label lines

CPU_COUNTER = r"\Processor Information(_Total)\% Processor Time"
GPU_COUNTER = r"\GPU Engine(*engtype_3D)\Utilization Percentage"

PATHS = (CPU_COUNTER, GPU_COUNTER)

PDH_FMT_DOUBLE = 0x00000200
GPU_PHYS = "_phys_0_"
RATE_SETTLE = 0.3  # s between the two collects a PDH rate counter needs

# Label/bar rows: label y, bar outline y (9px tall, so bar bottom y+8).
ROWS = ((0, 11), (21, 32), (42, 53))


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


def _kernel32():
    return ctypes.WinDLL("kernel32")


class Pdh:
    """One PDH query holding the monitored counters."""

    def __init__(self, paths=PATHS):
        self._pdh = ctypes.WinDLL("pdh")
        self._counters = {}
        self._q = wintypes.HANDLE()
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


class Nvml:
    """GPU temperature, read straight from NVML.

    No subprocess: `nvidia-smi` spawns a process and takes ~1s, which is the
    entire upload budget. A missing driver or non-NVIDIA GPU leaves `_lib`
    None and `temp_c()` returns None forever after one failed load.
    """

    SENSOR_TEMP_GPU = 0

    def __init__(self):
        self._lib = None
        self._dev = None
        try:
            lib = ctypes.WinDLL(os.path.join(
                os.environ.get("WINDIR", r"C:\Windows"), "System32",
                "nvml.dll"))
            lib.nvmlInit_v2.restype = ctypes.c_int
            if lib.nvmlInit_v2() != 0:
                return
            lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
                ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
            lib.nvmlDeviceGetTemperature.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
            lib.nvmlDeviceGetTemperature.restype = ctypes.c_int
            dev = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev)) != 0:
                return
            self._lib, self._dev = lib, dev
        except (OSError, AttributeError):
            self._lib = None

    def temp_c(self):
        if self._lib is None:
            return None
        v = ctypes.c_uint()
        if self._lib.nvmlDeviceGetTemperature(
                self._dev, self.SENSOR_TEMP_GPU, ctypes.byref(v)) != 0:
            return None
        return float(v.value)


_NVML = None


def _nvml():
    """Process-lifetime NVML handle, like the caller's PDH query."""
    global _NVML
    if _NVML is None:
        _NVML = Nvml()
    return _NVML


def _first(vals):
    return next(iter(vals.values())) if vals else None


def _max_where(vals, pred):
    hit = [v for k, v in vals.items() if pred(k)]
    return max(hit) if hit else None


def sample(pdh=None):
    """One system snapshot. Missing values become None (never raises)."""
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

    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(ms)
    total = avail = 0
    if _kernel32().GlobalMemoryStatusEx(ctypes.byref(ms)):
        total, avail = ms.ullTotalPhys, ms.ullAvailPhys
    ram_pct = (1.0 - avail / total) * 100.0 if total else 0.0

    return {"cpu": cpu, "gpu": gpu, "ram_pct": ram_pct,
            "ram_used_gb": (total - avail) / 2**30,
            "ram_total_gb": total / 2**30,
            "gpu_temp_c": _nvml().temp_c()}


def _pct(v):
    return "--" if v is None else f"{v:.0f}%"


def rows(stats):
    """The three label lines, "--" for anything absent."""
    temp = stats["gpu_temp_c"]
    return (f"CPU {_pct(stats['cpu'])}",
            f"GPU {_pct(stats['gpu'])}",
            f"RAM {_pct(stats['ram_pct'])}"
            + (f"  TEMP {temp:.0f}C" if temp is not None else "  TEMP --"))


def _row_font(d, *strings, maxw=122):
    """Largest of the small sizes that fits every string; rows never clip."""
    for sz in (SMALL, 9, 8):
        f = nowshow.font(sz)
        if all(nowshow.textw(d, s, f) <= maxw for s in strings):
            return f
    return nowshow.font(8)


def _bar(d, y, frac):
    d.rectangle([3, y, 124, y + 8], outline=255)
    w = int(118 * (0.0 if frac < 0 else 1.0 if frac > 1 else frac))
    if w:
        d.rectangle([5, y + 2, 5 + w, y + 6], fill=255)


def render(stats):
    """4 identical frames + meta. Never raises on missing values."""
    labels = rows(stats)
    fractions = ((stats["cpu"] or 0.0) / 100.0,
                 (stats["gpu"] or 0.0) / 100.0,
                 (stats["ram_pct"] or 0.0) / 100.0)
    im, d = nowshow.new()
    f = _row_font(d, *labels)
    for lab, ((ly, by), frac) in zip(labels, zip(ROWS, fractions)):
        d.text((3, ly), lab, font=f, fill=255)
        _bar(d, by, frac)
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
    for k in ("cpu", "gpu", "ram_pct", "ram_used_gb", "ram_total_gb",
              "gpu_temp_c"):
        print(f"  {k}={stats[k]!r}")
    print(f"  rows={rows(stats)}")
    print(f"render_time={time.time() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")
PROC_STAT = Path("/proc/stat")
MEMINFO = Path("/proc/meminfo")
# bits of vcgencmd get_throttled: low voltage right now, and low voltage at some point since boot
LOW_NOW = 0x1
LOW_SINCE_BOOT = 0x10000


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def low_voltage(run: Callable = subprocess.run) -> bool | None:
    # the pi itself notices when its 5 V input sags below about 4.63 V, None off a pi
    if shutil.which("vcgencmd") is None:
        return None
    try:
        out = run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", out or "")
    if m is None:
        return None
    return bool(int(m.group(1), 16) & (LOW_NOW | LOW_SINCE_BOOT))


class SysInfo:
    # cpu in percent of the whole machine, temperature in degrees celsius, memory in percent used,
    # anything the platform does not offer stays None

    def __init__(self) -> None:
        self._prev: tuple[float, float] | None = None
        self._win = None
        if sys.platform == "win32":
            try:
                self._win = _Win()
            except Exception:
                self._win = None

    def sample(self) -> dict:
        return {"cpu": self.cpu(), "temp": self.temp(), "mem": self.mem()}

    def cpu(self) -> float | None:
        times = self._cpu_times()
        if times is None:
            return None
        busy, total = times
        prev = self._prev
        self._prev = times
        if prev is None or total <= prev[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (busy - prev[0]) / (total - prev[1])))

    def _cpu_times(self) -> tuple[float, float] | None:
        if self._win is not None:
            return self._win.cpu_times()
        text = _read(PROC_STAT)
        if not text:
            return None
        first = text.split("\n", 1)[0].split()
        if not first or first[0] != "cpu":
            return None
        vals = [float(x) for x in first[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)
        total = sum(vals[:8])
        return total - idle, total

    def temp(self) -> float | None:
        text = _read(THERMAL)
        if not text:
            return None
        try:
            return int(text.strip()) / 1000.0
        except ValueError:
            return None

    def mem(self) -> float | None:
        if self._win is not None:
            return self._win.mem()
        text = _read(MEMINFO)
        if not text:
            return None
        info = {}
        for line in text.splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                try:
                    info[key] = float(parts[0])
                except ValueError:
                    pass
        total = info.get("MemTotal")
        avail = info.get("MemAvailable")
        if not total or avail is None:
            return None
        return 100.0 * (total - avail) / total


class _Win:
    # the same numbers on windows through the kernel32 calls, only used for development

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.k32 = ctypes.windll.kernel32

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

        class MEMSTAT(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        self.FILETIME = FILETIME
        self.MEMSTAT = MEMSTAT

    def cpu_times(self) -> tuple[float, float] | None:
        ft = self.FILETIME
        idle, kernel, user = ft(), ft(), ft()
        ok = self.k32.GetSystemTimes(
            self.ctypes.byref(idle), self.ctypes.byref(kernel), self.ctypes.byref(user)
        )
        if not ok:
            return None

        def v(x):
            return float((x.hi << 32) | x.lo)

        total = v(kernel) + v(user)  # kernel time already includes idle time
        return total - v(idle), total

    def mem(self) -> float | None:
        st = self.MEMSTAT()
        st.dwLength = self.ctypes.sizeof(self.MEMSTAT)
        if not self.k32.GlobalMemoryStatusEx(self.ctypes.byref(st)):
            return None
        if not st.ullTotalPhys:
            return None
        return 100.0 * (st.ullTotalPhys - st.ullAvailPhys) / st.ullTotalPhys


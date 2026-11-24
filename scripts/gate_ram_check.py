"""Free-RAM check before the full gate (owner rule 2026-11-24, this laptop).

`make check` runs this first. Under the limit it re-checks for up to 10 minutes, then stops
with a report instead of starting: a gate killed half way for low memory proves nothing.
Standard library only; the Windows reading uses GlobalMemoryStatusEx.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Callable, Mapping

MIN_FREE_GB = 3.0
WAIT_S = 600
RECHECK_S = 30
MIN_ENV = "TJ_GATE_MIN_FREE_GB"
WAIT_ENV = "TJ_GATE_WAIT_S"
GB = 1024**3


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_gb() -> float | None:
    """Available physical memory in GB; None when it cannot be read (not Windows, API error)."""
    if sys.platform != "win32":
        return None
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return float(status.ullAvailPhys) / GB


def _number(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(env.get(name, default))
    except ValueError:
        return default


def _say(text: str) -> None:
    print(text, flush=True)  # make shows each line at once


def wait_for_memory(
    env: Mapping[str, str],
    read: Callable[[], float | None] = free_gb,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] | None = None,
) -> bool:
    """True when the gate may start. Re-checks every 30 s up to the wait limit."""
    if say is None:
        say = _say
    need = _number(env, MIN_ENV, MIN_FREE_GB)
    budget = _number(env, WAIT_ENV, WAIT_S)
    waited = 0.0
    while True:
        free = read()
        if free is None:
            say("[gate] Free RAM unknown on this system: starting the gate without the check.")
            return True
        if free >= need:
            say(f"[gate] Free RAM {free:.1f} GB (limit {need:.1f} GB): starting.")
            return True
        if waited >= budget:
            say(
                f"[gate] NOT STARTED: free RAM {free:.1f} GB is under {need:.1f} GB after waiting "
                f"{waited / 60:.0f} min. Free memory (close heavy apps) and run make check again."
            )
            return False
        say(f"[gate] Free RAM {free:.1f} GB is under {need:.1f} GB: re-checking in {RECHECK_S} s.")
        sleep(RECHECK_S)
        waited += RECHECK_S


def main() -> int:
    return 0 if wait_for_memory(os.environ) else 1


if __name__ == "__main__":
    sys.exit(main())

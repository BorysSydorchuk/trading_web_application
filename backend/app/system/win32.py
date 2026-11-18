"""Thin ctypes layer over the Win32 calls M8-12 needs (no new dependency).

Only the functions below touch Win32; everything else in ``app.system`` takes a ``Win32``
object so tests can pass a fake. On non-Windows platforms ``native()`` returns None.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SW_HIDE = 0
SW_SHOW = 5


@dataclass(frozen=True)
class ProcessId:
    """A process, identified by PID plus creation time (a PID alone can be reused)."""

    pid: int
    created: int


class Win32(Protocol):
    def processes_of(self, exe: Path) -> set[ProcessId]: ...

    def alive(self, proc: ProcessId) -> bool: ...

    def windows_of(self, pid: int) -> list[int]: ...

    def is_visible(self, hwnd: int) -> bool: ...

    def show(self, hwnd: int, command: int) -> None: ...


def _same_path(a: str, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except OSError:
        return a.lower() == str(b).lower()


if sys.platform == "win32":
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _TH32CS_SNAPPROCESS = 0x00000002
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _GW_OWNER = 4

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.OpenProcess.restype = wintypes.HANDLE
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class NativeWin32:
        """The real Win32 implementation (read process list, hide/show top-level windows)."""

        def _pids_named(self, name: str) -> list[int]:
            snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
            if snap in (None, wintypes.HANDLE(-1).value):
                return []
            pids: list[int] = []
            try:
                entry = _ProcessEntry()
                entry.dwSize = ctypes.sizeof(_ProcessEntry)
                ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    if entry.szExeFile.lower() == name.lower():
                        pids.append(int(entry.th32ProcessID))
                    ok = _k32.Process32NextW(snap, ctypes.byref(entry))
            finally:
                _k32.CloseHandle(snap)
            return pids

        def _query(self, pid: int) -> tuple[str, int] | None:
            """(full image path, creation time) of a live process, or None."""
            handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return None
            try:
                code = wintypes.DWORD(0)
                if _k32.GetExitCodeProcess(handle, ctypes.byref(code)) and (
                    code.value != _STILL_ACTIVE
                ):
                    return None
                times = [wintypes.FILETIME() for _ in range(4)]
                if not _k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    return None
                created = (int(times[0].dwHighDateTime) << 32) | int(times[0].dwLowDateTime)
                size = wintypes.DWORD(32768)
                buf = ctypes.create_unicode_buffer(size.value)
                if not _k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return None
                return buf.value, created
            finally:
                _k32.CloseHandle(handle)

        def processes_of(self, exe: Path) -> set[ProcessId]:
            found: set[ProcessId] = set()
            for pid in self._pids_named(exe.name):
                info = self._query(pid)
                if info is not None and _same_path(info[0], exe):
                    found.add(ProcessId(pid, info[1]))
            return found

        def alive(self, proc: ProcessId) -> bool:
            info = self._query(proc.pid)
            return info is not None and info[1] == proc.created

        def windows_of(self, pid: int) -> list[int]:
            """Top-level, unowned windows of ``pid`` (the terminal's main window)."""
            found: list[int] = []

            def collect(hwnd: int, _: int) -> bool:
                owner = wintypes.DWORD(0)
                _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value == pid and not _u32.GetWindow(hwnd, _GW_OWNER):
                    found.append(int(hwnd))
                return True

            _u32.EnumWindows(_EnumProc(collect), 0)
            return found

        def is_visible(self, hwnd: int) -> bool:
            return bool(_u32.IsWindowVisible(hwnd))

        def show(self, hwnd: int, command: int) -> None:
            _u32.ShowWindow(hwnd, command)


def native() -> Win32 | None:
    """The real Win32 layer on Windows, None elsewhere (the features are then no-ops)."""
    if sys.platform != "win32":
        return None
    return NativeWin32()

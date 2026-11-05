"""Dev launcher for the Trading Journal app (used by `start.bat`, `stop.bat` and `make dev`).

Stdlib only, Python 3.12+. Steps:
  1. stops a previous run of this app (recorded in `logs/dev-run.json`, or an orphaned
     API/UI process of this checkout still holding port 8000/5173),
  2. prerequisite checks (Python, Node/npm, uv),
  3. `.env` from `.env.example` if missing,
  4. `uv sync` / `npm install` when dependencies are missing or stale,
  5. PostgreSQL reachable (starts Docker Desktop and the `db` service if needed) +
     `alembic upgrade head`,
  6. starts API, worker and Vite dev server with prefixed output,
  7. waits for http://127.0.0.1:8000/api/health and http://127.0.0.1:5173/, opens the browser.

Ctrl+C (or any child exiting) stops everything; on Windows whole process trees are killed.

Usage:
  python scripts/dev.py               start everything and open the browser
  python scripts/dev.py --no-browser  same, without opening the browser
  python scripts/dev.py --ensure-db   only make sure the DB is up and migrated, then exit
  python scripts/dev.py --stop        stop a running app (what stop.bat does)

Run file: the launcher records its own PID and every child PID with the process creation
time and command line. A recorded PID is trusted as "ours" only when both still match, so a
reused PID is never killed. Console messages for the user are Ukrainian (MSG below); code
comments and child logs stay English.
"""

# Only fixed commands (uv, npm, docker, taskkill) are executed; no user input reaches them.
# ruff: noqa: S603, S607, RUF001
# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
LOGS = ROOT / "logs"  # gitignored
RUN_FILE = LOGS / "dev-run.json"
STOP_REQUEST_FILE = LOGS / "dev-stop-request.json"

# Fixed by frontend/vite.config.ts (strictPort + /api proxy target); keep in sync.
API_HOST = "127.0.0.1"
API_PORT = 8000
WEB_PORT = 5173
APP_PORTS = (API_PORT, WEB_PORT)
HEALTH_URL = f"http://{API_HOST}:{API_PORT}/api/health"
WEB_URL = f"http://{API_HOST}:{WEB_PORT}/"

READY_TIMEOUT_S = 60.0
DOCKER_START_TIMEOUT_S = 60.0
DB_TCP_TIMEOUT_S = 30.0
GRACEFUL_STOP_S = 15.0  # a running launcher gets this long to stop its children itself
PROCESS_EXIT_TIMEOUT_S = 10.0
PORT_FREE_TIMEOUT_S = 15.0
MIN_NODE = (20, 19)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
RUN_FILE_VERSION = 1

BACKEND_STAMP = BACKEND / ".venv" / ".dev-sync-stamp"
FRONTEND_STAMP = FRONTEND / "node_modules" / ".dev-install-stamp"

IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------------- messages
# Every user-facing console message of the launcher (Ukrainian). `{...}` are str.format fields.
# Never put DATABASE_URL (or parts of it) into a message: it may contain the password.

DB_URL_ERROR = (
    "не вдалося прочитати хост/порт з DATABASE_URL; очікується "
    "postgresql+psycopg://user:password@host:5432/db, а спецсимволи (/ # ? @ :) у паролі "
    "треба закодувати (URL-encode, напр. / → %2F)"
)

MSG: dict[str, str] = {
    # prerequisites
    "python_old": "Потрібен Python 3.12+, знайдено {found}. Див. README (Prerequisites).",
    "uv_missing": (
        "Не знайдено uv. Встановіть його (PowerShell): "
        'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" '
        "і відкрийте новий термінал. Див. README."
    ),
    "node_missing": (
        "Не знайдено Node.js/npm. Встановіть Node LTS: winget install OpenJS.NodeJS.LTS "
        "і відкрийте новий термінал. Див. README."
    ),
    "node_version_failed": "Не вдалося виконати `node --version`: {error}",
    "node_old": (
        "Потрібен Node {need}+ (Vite 8), знайдено {found}. "
        "Встановіть актуальний LTS: winget install OpenJS.NodeJS.LTS"
    ),
    # .env and setup steps
    "env_missing": "Немає ні .env, ні .env.example. Це повний клон репозиторію?",
    "env_created": (
        "Створено .env з .env.example (відредагуйте його, щоб змінити налаштування БД "
        "або додати API-ключі)."
    ),
    "step_running": "{what}…",
    "step_timeout": "{what}: перевищено час очікування ({timeout} с).",
    "step_cannot_start": "{what}: не вдалося запустити ({error}).",
    "step_failed": "{what}: помилка (код виходу {code}); див. вивід вище.",
    "step_uv_sync": "Встановлюю залежності бекенду (uv sync)",
    "step_npm_install": "Встановлюю залежності фронтенду (npm install)",
    "step_compose_up": "Запускаю PostgreSQL у Docker (docker compose up -d --wait db)",
    "step_migrate": "Застосовую міграції БД (alembic upgrade head)",
    # database / Docker
    "db_url_missing": "DATABASE_URL не задано в .env (див. .env.example).",
    "db_url_invalid": "Некоректний DATABASE_URL: " + DB_URL_ERROR + ".",
    "db_reachable": "PostgreSQL доступний на {host}:{port}.",
    "db_no_docker": (
        "PostgreSQL недоступний на {host}:{port}. Встановіть Docker Desktop або PostgreSQL 16 "
        "і вкажіть DATABASE_URL у .env. Див. README."
    ),
    "db_remote": (
        "PostgreSQL недоступний на {host}:{port}. DATABASE_URL вказує на віддалений сервер; "
        "переконайтеся, що він працює. Див. README."
    ),
    "docker_starting": "Docker Desktop не запущено — запускаю, чекаю до {seconds} с…",
    "docker_started": "Docker Desktop запущено.",
    "docker_cannot_start": (
        "PostgreSQL недоступний на {host}:{port}, а Docker Desktop не запущено, і запустити "
        "його автоматично не вдалося. Запустіть Docker Desktop, дочекайтеся «Engine running» "
        "і спробуйте знову."
    ),
    "docker_timeout": (
        "Docker Desktop не запустився за {seconds} с. Відкрийте Docker Desktop, дочекайтеся "
        "«Engine running» і запустіть застосунок знову."
    ),
    "db_still_unreachable": (
        "Docker запустив сервіс db, але {host}:{port} досі недоступний. Перевірте "
        "POSTGRES_PORT і DATABASE_URL у .env, а також `docker compose logs db`."
    ),
    # previous run / ports
    "prev_run_found": "Знайдено попередній запуск застосунку: {procs}. Зупиняю його…",
    "prev_launcher_asked": (
        "Попросив попередній лаунчер (PID {pid}) зупинитися, чекаю до {seconds} с…"
    ),
    "orphan_found": "Порт {port} тримає процес попереднього запуску: {proc}. Зупиняю…",
    "orphan_worker_found": "Знайдено воркер попереднього запуску: {proc}. Зупиняю…",
    "stopped_proc": "Зупинено: {proc}.",
    "stop_failed": "Не вдалося зупинити {proc}: {error}",
    "proc_still_running": "процес досі працює",
    "prev_run_survived": (
        "Не вдалося зупинити процеси попереднього запуску: {procs}. Закрийте їх вручну "
        "(Диспетчер завдань) і запустіть знову; інакше працювали б два воркери "
        "(подвійна синхронізація MT5)."
    ),
    "stop_incomplete": (
        "Зупинено не все: {procs} досі працюють. Закрийте їх вручну (Диспетчер завдань)."
    ),
    "waiting_ports": "Чекаю, поки звільняться порти {ports}…",
    "port_foreign": (
        "Порт {port} зайнятий іншою програмою: {proc}. Це не процес застосунку, тому його не "
        "зупинено. Закрийте цю програму (або `taskkill /PID {pid} /F`) і запустіть знову."
    ),
    "port_foreign_stop": "Порт {port} зайнятий іншою програмою: {proc}. Її не зупинено.",
    "port_unknown": (
        "Порт {port} зайнятий, але процес визначити не вдалося. Знайдіть його: "
        "`netstat -ano | findstr :{port}`, зупиніть (`taskkill /PID <pid> /F`) і запустіть знову."
    ),
    "ports_not_freed": (
        "Порти {ports} не звільнилися за {seconds} с після зупинки попереднього запуску. "
        "Спробуйте stop.bat ще раз або перезавантажте комп'ютер."
    ),
    "stop_nothing": "Застосунок не запущено, нічого зупиняти.",
    "stop_done": "Застосунок зупинено.",
    "stop_request_received": "Отримано запит на зупинку (stop.bat або новий запуск) — зупиняю…",
    # children
    "child_cannot_start": "Не вдалося запустити {name}: {error}",
    "child_exited": (
        "{name} несподівано завершився (код виходу {code}); див. його вивід вище та logs/."
    ),
    "child_stop_failed": "Не вдалося зупинити {name} (PID {pid}): {error}",
    "stopping": "Зупиняю…",
    "all_stopped": "Усі процеси зупинено.",
    "ready_timeout": (
        "За {seconds} с не дочекався відповіді від {missing}. Див. вивід вище та logs/."
    ),
    "ready_missing_api": "API ({url})",
    "ready_missing_web": "фронтенду ({url})",
    "ready_join": " і ",
    "ready": "Готово за {elapsed} с: {url} (стан API: {health})",
    "health_warning": ("УВАГА: стан API не 'ok' (проблема з базою даних?); див. logs/api.log."),
    "press_ctrl_c": "Натисніть Ctrl+C, щоб зупинити.",
    "error": "ПОМИЛКА: {error}",
    "interrupted": "Перервано.",
    # argparse
    "help_description": "Запуск Trading Journal для розробки.",
    "help_no_browser": "не відкривати браузер",
    "help_ensure_db": "лише переконатися, що PostgreSQL запущено і міграції застосовано",
    "help_stop": "зупинити запущений застосунок (як stop.bat)",
    # process descriptions
    "proc_desc": "{name} (PID {pid})",
    "proc_unknown_name": "невідомий процес",
}


class LauncherError(Exception):
    """A readable, expected failure: printed without a traceback, exit code 1."""


class StopRequested(Exception):  # noqa: N818 - a signal, not an error
    """Another launcher (`--stop` or a new start) asked this one to stop."""


# --------------------------------------------------------------------------- output

_print_lock = threading.Lock()


def say(msg: str) -> None:
    with _print_lock:
        print(f"[dev] {msg}", flush=True)


# --------------------------------------------------------------------------- pure helpers


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a simple dotenv file: KEY=VALUE lines, `#` comments, optional quotes."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def parse_db_host_port(url: str) -> tuple[str, int]:
    """Host and port of a SQLAlchemy/libpq style URL (`postgresql+psycopg://u:p@h:5432/db`).

    Defaults: host `localhost`, port 5432. Raises ValueError with a fixed message (never
    containing parts of the URL, which may hold the password) for a malformed URL.
    """
    scheme, sep, rest = url.partition("://")
    if not sep or not scheme.startswith("postgres"):
        raise ValueError(DB_URL_ERROR)
    parts = urlsplit(url)
    # An unencoded / # ? in the password ends the netloc early: the '@' then sits in the
    # path/query/fragment and part of the password would be read as host or port.
    if "@" in rest and "@" not in parts.netloc:
        raise ValueError(DB_URL_ERROR)
    try:
        port = parts.port or 5432  # raises for a non-numeric or out-of-range port
    except ValueError:
        raise ValueError(DB_URL_ERROR) from None
    return parts.hostname or "localhost", port


def needs_install(stamp: Path, manifests: Sequence[Path]) -> bool:
    """True if `stamp` is missing or any existing manifest is newer than it."""
    if not stamp.exists():
        return True
    stamp_mtime = stamp.stat().st_mtime
    return any(m.exists() and m.stat().st_mtime > stamp_mtime for m in manifests)


def parse_node_version(text: str) -> tuple[int, int]:
    """`v22.12.0` -> (22, 12)."""
    parts = text.strip().lstrip("v").split(".")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def is_local_host(host: str) -> bool:
    return host.lower() in LOCAL_HOSTS


# --------------------------------------------------------------------------- process queries
# Windows: ctypes only (Toolhelp snapshot, OpenProcess/GetProcessTimes,
# NtQueryInformationProcess(ProcessCommandLineInformation), GetExtendedTcpTable); all calls
# are local and take milliseconds. Other platforms: no process data, so a busy port is
# always reported as a readable error and nothing is ever killed automatically.


@dataclass(frozen=True)
class ProcInfo:
    """A live process. create_time (FILETIME ticks) / cmdline are None if access is denied."""

    pid: int
    name: str
    create_time: int | None
    cmdline: str | None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _TH32CS_SNAPPROCESS = 0x2
    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _PROCESS_COMMAND_LINE_INFORMATION = 60
    _TCP_TABLE_OWNER_PID_LISTENER = 3
    _ERROR_INSUFFICIENT_BUFFER = 122
    _AF_INET6 = 23

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", ctypes.c_void_p),
        )

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _iphlp = ctypes.WinDLL("iphlpapi")

    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _k32.GetExitCodeProcess.restype = wintypes.BOOL
    _k32.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    _k32.GetProcessTimes.restype = wintypes.BOOL
    _k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W))
    _k32.Process32FirstW.restype = wintypes.BOOL
    _k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W))
    _k32.Process32NextW.restype = wintypes.BOOL
    _ntdll.NtQueryInformationProcess.argtypes = (
        wintypes.HANDLE,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    )
    _ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    _iphlp.GetExtendedTcpTable.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    )
    _iphlp.GetExtendedTcpTable.restype = wintypes.DWORD

    def _win_process_names() -> dict[int, str]:
        names: dict[int, str] = {}
        snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snap or snap == _INVALID_HANDLE:
            return names
        try:
            entry = _ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
            ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                names[int(entry.th32ProcessID)] = str(entry.szExeFile)
                ok = _k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            _k32.CloseHandle(snap)
        return names

    def _win_cmdline(handle: int) -> str | None:
        size = 2048
        for _ in range(3):
            buf = ctypes.create_string_buffer(size)
            needed = wintypes.ULONG(0)
            status = _ntdll.NtQueryInformationProcess(
                handle, _PROCESS_COMMAND_LINE_INFORMATION, buf, size, ctypes.byref(needed)
            )
            if status == 0:
                text = _UnicodeString.from_buffer(buf)
                if not text.Buffer or not text.Length:
                    return ""
                return str(ctypes.wstring_at(text.Buffer, int(text.Length) // 2))
            if needed.value <= size:
                return None
            size = int(needed.value)
        return None

    def _win_query_process(pid: int) -> ProcInfo | None:
        handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        name = _win_process_names().get(pid)
        if not handle:
            # No access (e.g. System, elevated or another user's process): name only.
            return None if name is None else ProcInfo(pid, name, None, None)
        try:
            code = wintypes.DWORD(0)
            if _k32.GetExitCodeProcess(handle, ctypes.byref(code)) and (
                code.value != _STILL_ACTIVE
            ):
                return None  # exited; the handle only keeps the process object around
            times = [wintypes.FILETIME() for _ in range(4)]
            create_time: int | None = None
            if _k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                create_time = (int(times[0].dwHighDateTime) << 32) | int(times[0].dwLowDateTime)
            cmdline = _win_cmdline(handle)
        finally:
            _k32.CloseHandle(handle)
        return ProcInfo(pid, name or MSG["proc_unknown_name"], create_time, cmdline)

    def _win_tcp_table(family: int) -> bytes:
        size = wintypes.DWORD(0)
        _iphlp.GetExtendedTcpTable(
            None, ctypes.byref(size), False, family, _TCP_TABLE_OWNER_PID_LISTENER, 0
        )
        for _ in range(5):
            buf = ctypes.create_string_buffer(max(int(size.value), 4))
            rc = _iphlp.GetExtendedTcpTable(
                buf, ctypes.byref(size), False, family, _TCP_TABLE_OWNER_PID_LISTENER, 0
            )
            if rc == 0:
                return bytes(buf.raw)
            if rc != _ERROR_INSUFFICIENT_BUFFER:
                return b""
        return b""


# Row layouts of MIB_TCPROW_OWNER_PID / MIB_TCP6ROW_OWNER_PID: (row size, port offset, pid offset).
TCP4_ROW = (24, 8, 20)
TCP6_ROW = (56, 20, 52)


def parse_tcp_owner_table(raw: bytes, row: tuple[int, int, int], port: int) -> set[int]:
    """PIDs listening on `port` in a raw GetExtendedTcpTable(TCP_TABLE_OWNER_PID_*) buffer."""
    size, port_off, pid_off = row
    if len(raw) < 4:
        return set()
    count = struct.unpack_from("<I", raw, 0)[0]
    pids: set[int] = set()
    for i in range(count):
        off = 4 + i * size
        if off + size > len(raw):
            break
        # The port is a DWORD whose low 2 bytes hold the port in network byte order.
        if int.from_bytes(raw[off + port_off : off + port_off + 2], "big") == port:
            pids.add(struct.unpack_from("<I", raw, off + pid_off)[0])
    return pids


def query_process(pid: int) -> ProcInfo | None:
    """Live process data, or None if no such (running) process."""
    if sys.platform != "win32":
        return None
    try:
        return _win_query_process(pid)
    except OSError:
        return None


def process_names() -> dict[int, str]:
    """Image name of every running process by PID."""
    if sys.platform != "win32":
        return {}
    try:
        return _win_process_names()
    except OSError:
        return {}


def listening_pids(port: int) -> set[int]:
    """PIDs with a TCP socket listening on `port` (IPv4 or IPv6)."""
    if sys.platform != "win32":
        return set()
    try:
        return parse_tcp_owner_table(
            _win_tcp_table(socket.AF_INET), TCP4_ROW, port
        ) | parse_tcp_owner_table(_win_tcp_table(_AF_INET6), TCP6_ROW, port)
    except OSError:
        return set()


def kill_process_tree(pid: int) -> str | None:
    """Force-stop a process and all its descendants. Returns an error text, None if OK.

    Callers must still check that the process is gone: taskkill also fails for a process
    that has already exited, and "success" is only a request to the OS.
    """
    if sys.platform != "win32":
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return None
        except PermissionError as exc:
            return str(exc)
        return None
    try:
        result = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    text = (result.stderr or result.stdout).decode("oem", errors="replace").strip()
    return text or f"taskkill: код виходу {result.returncode}"


def describe(info: ProcInfo | None, pid: int) -> str:
    return MSG["proc_desc"].format(name=info.name if info else MSG["proc_unknown_name"], pid=pid)


def normalize_cmdline(text: str) -> str:
    return text.replace("/", "\\").lower() if IS_WINDOWS else text


def is_app_process(info: ProcInfo, root: Path | None = None) -> bool:
    """True for an API/UI process of this checkout (its command line has backend/ or frontend/).

    Used for port holders that are not in the run file (orphans whose parent died, or a
    launcher killed before writing the file). A different checkout never matches.
    """
    if not info.cmdline:
        return False
    base = root or ROOT
    cmd = normalize_cmdline(info.cmdline)
    sep = "\\" if IS_WINDOWS else "/"
    return any(normalize_cmdline(str(base / sub)) + sep in cmd for sub in ("backend", "frontend"))


def is_worker_process(info: ProcInfo, root: Path | None = None) -> bool:
    """True for the sync worker of this checkout (`backend/.venv` python `-m app.worker`).

    The worker holds no port, so without the run file this is the only way to find an
    orphaned one (two workers would sync MT5 twice).
    """
    if not info.cmdline:
        return False
    sep = "\\" if IS_WINDOWS else "/"
    venv = normalize_cmdline(str((root or ROOT) / "backend" / ".venv")) + sep
    cmd = normalize_cmdline(info.cmdline)
    return venv in cmd and cmd.rstrip().endswith("-m app.worker")


def find_orphan_workers() -> list[ProcInfo]:
    me = os.getpid()
    found: list[ProcInfo] = []
    for pid, name in process_names().items():
        if pid == me or not name.lower().startswith("python"):
            continue
        info = query_process(pid)
        if info is not None and is_worker_process(info):
            found.append(info)
    return found


# --------------------------------------------------------------------------- run file


@dataclass(frozen=True)
class RunRecord:
    role: str  # launcher | web | api | worker
    pid: int
    create_time: int
    cmdline: str


def make_record(role: str, pid: int) -> RunRecord | None:
    info = query_process(pid)
    if info is None or info.create_time is None or info.cmdline is None:
        return None
    return RunRecord(role, pid, info.create_time, info.cmdline)


def write_run_file(path: Path, records: Sequence[RunRecord]) -> None:
    data = {
        "version": RUN_FILE_VERSION,
        "root": str(ROOT),
        "started_at": datetime.now(UTC).isoformat(),
        "ports": list(APP_PORTS),
        "processes": [asdict(r) for r in records],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_run_file(path: Path) -> list[RunRecord]:
    """Records of the run file; [] if missing, unreadable or from another checkout."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != RUN_FILE_VERSION or data.get("root") != str(ROOT):
            return []
        return [
            RunRecord(str(p["role"]), int(p["pid"]), int(p["create_time"]), str(p["cmdline"]))
            for p in data["processes"]
        ]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []


def remove_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def is_recorded_process(record: RunRecord, info: ProcInfo | None) -> bool:
    """The live process is the recorded one: same PID, creation time and command line.

    A reused PID has a different creation time (and usually command line), so it is rejected.
    """
    return (
        info is not None
        and info.pid == record.pid
        and info.create_time == record.create_time
        and info.cmdline == record.cmdline
    )


def alive_records(records: Iterable[RunRecord]) -> list[tuple[RunRecord, ProcInfo]]:
    result: list[tuple[RunRecord, ProcInfo]] = []
    for record in records:
        if record.pid == os.getpid():
            continue
        info = query_process(record.pid)
        if info is not None and is_recorded_process(record, info):
            result.append((record, info))
    return result


def wait_records_gone(records: Sequence[RunRecord], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        if not alive_records(records):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


# --------------------------------------------------------------------------- previous run


@dataclass
class PortHolders:
    ours: dict[int, list[ProcInfo]] = field(default_factory=dict)
    foreign: dict[int, list[tuple[int, ProcInfo | None]]] = field(default_factory=dict)


def classify_port_holders(ports: Iterable[int]) -> PortHolders:
    """Split the listeners of `ports` into processes of this app (ours) and anything else."""
    result = PortHolders()
    me = os.getpid()
    for port in ports:
        for pid in sorted(listening_pids(port)):
            if pid == me:
                continue
            info = query_process(pid)
            if info is not None and is_app_process(info):
                result.ours.setdefault(port, []).append(info)
            else:
                result.foreign.setdefault(port, []).append((pid, info))
    return result


def request_launcher_stop(record: RunRecord) -> bool:
    """Ask a running launcher to stop its children itself (cleaner than killing it)."""
    try:
        STOP_REQUEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_REQUEST_FILE.write_text(
            json.dumps({"pid": record.pid, "create_time": record.create_time}), encoding="utf-8"
        )
    except OSError:
        return False
    say(MSG["prev_launcher_asked"].format(pid=record.pid, seconds=f"{GRACEFUL_STOP_S:.0f}"))
    try:
        return wait_records_gone([record], GRACEFUL_STOP_S)
    finally:
        remove_file(STOP_REQUEST_FILE)


def stop_requested(own: RunRecord | None) -> bool:
    """True if another launcher asked this one (by PID + creation time) to stop."""
    if own is None:
        return False
    try:
        data = json.loads(STOP_REQUEST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and data.get("pid") == own.pid
        and data.get("create_time") == own.create_time
    )


@dataclass(frozen=True)
class StopTarget:
    """A process we decided to stop, identified by PID + creation time + command line."""

    pid: int
    create_time: int | None
    cmdline: str | None
    label: str


@dataclass
class StopResult:
    stopped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def target_running(target: StopTarget) -> bool:
    info = query_process(target.pid)
    return (
        info is not None
        and info.create_time == target.create_time
        and info.cmdline == target.cmdline
    )


def stop_targets(targets: Sequence[StopTarget], result: StopResult) -> None:
    """taskkill each target's tree, then report each one as stopped only if it is gone."""
    errors: dict[int, str] = {}
    for target in targets:
        if target_running(target):
            error = kill_process_tree(target.pid)
            if error:
                errors[target.pid] = error
    deadline = time.monotonic() + PROCESS_EXIT_TIMEOUT_S
    left = list(targets)
    while True:
        left = [t for t in left if target_running(t)]
        if not left or time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    for target in targets:
        if target in left:
            error = errors.get(target.pid) or MSG["proc_still_running"]
            say(MSG["stop_failed"].format(proc=target.label, error=error))
            result.failed.append(target.label)
        else:
            say(MSG["stopped_proc"].format(proc=target.label))
            result.stopped.append(target.label)


def _target(info: ProcInfo, label: str) -> StopTarget:
    return StopTarget(info.pid, info.create_time, info.cmdline, label)


def stop_previous_run() -> StopResult:
    """Stop our previous run: recorded processes (verified), orphaned app port holders and
    an orphaned worker of this checkout.

    Never touches a process that is not provably ours. A process is reported as stopped only
    after it is verified gone; survivors land in `failed`.
    """
    result = StopResult()
    alive = alive_records(read_run_file(RUN_FILE))
    if alive:
        procs = ", ".join(f"{r.role} {describe(i, r.pid)}" for r, i in alive)
        say(MSG["prev_run_found"].format(procs=procs))
        targets = [
            StopTarget(r.pid, r.create_time, r.cmdline, f"{r.role} {describe(i, r.pid)}")
            for r, i in alive
        ]
        launcher = next((r for r, _ in alive if r.role == "launcher"), None)
        if launcher is not None:
            # A running launcher stops its own children; whatever is left is force-stopped
            # below, the launcher first so its whole tree goes with it.
            request_launcher_stop(launcher)
            targets.sort(key=lambda t: t.pid != launcher.pid)
        stop_targets(targets, result)
    remove_file(RUN_FILE)

    orphans: list[StopTarget] = []
    for port, infos in classify_port_holders(APP_PORTS).ours.items():
        for info in infos:
            label = describe(info, info.pid)
            say(MSG["orphan_found"].format(port=port, proc=label))
            orphans.append(_target(info, label))
    for info in find_orphan_workers():
        label = describe(info, info.pid)
        say(MSG["orphan_worker_found"].format(proc=label))
        orphans.append(_target(info, label))
    stop_targets(orphans, result)
    return result


def busy_ports(ports: Iterable[int] = APP_PORTS) -> list[int]:
    return [p for p in ports if port_in_use(p)]


def wait_ports_free(timeout_s: float) -> list[int]:
    deadline = time.monotonic() + timeout_s
    while True:
        busy = busy_ports()
        if not busy or time.monotonic() >= deadline:
            return busy
        time.sleep(0.25)


def foreign_port_messages(ports: Sequence[int], template: str) -> list[str]:
    holders = classify_port_holders(ports)
    messages: list[str] = []
    for port in ports:
        found = holders.foreign.get(port, [])
        if not found:
            messages.append(MSG["port_unknown"].format(port=port))
        for pid, info in found:
            messages.append(MSG[template].format(port=port, proc=describe(info, pid), pid=pid))
    return messages


def ensure_ports_free() -> None:
    """Stop our previous run if any; fail with a readable error if a foreign app holds a port."""
    result = stop_previous_run()
    if result.failed:
        raise LauncherError(MSG["prev_run_survived"].format(procs=", ".join(result.failed)))
    stopped = result.stopped
    busy = busy_ports()
    if busy and stopped:
        say(MSG["waiting_ports"].format(ports=", ".join(map(str, busy))))
        busy = wait_ports_free(PORT_FREE_TIMEOUT_S)
    if not busy:
        return
    messages = foreign_port_messages(busy, "port_foreign")
    if stopped and not any(classify_port_holders(busy).foreign.values()):
        messages = [
            MSG["ports_not_freed"].format(
                ports=", ".join(map(str, busy)), seconds=f"{PORT_FREE_TIMEOUT_S:.0f}"
            )
        ]
    raise LauncherError(" ".join(messages))


def run_stop() -> int:
    result = stop_previous_run()
    remove_file(STOP_REQUEST_FILE)
    if result.failed:
        say(MSG["stop_incomplete"].format(procs=", ".join(result.failed)))
        return 1
    busy = wait_ports_free(PORT_FREE_TIMEOUT_S) if result.stopped else busy_ports()
    say(MSG["stop_done"] if result.stopped else MSG["stop_nothing"])
    for message in foreign_port_messages(busy, "port_foreign_stop") if busy else []:
        say(message)
    return 0


# --------------------------------------------------------------------------- environment


def load_env() -> dict[str, str]:
    """Values from `.env`, overridden by the process environment (same as pydantic-settings)."""
    values = parse_env_file(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.exists() else {}
    for key in {*values, "DATABASE_URL", "TEST_DATABASE_URL"}:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    if not ENV_EXAMPLE.exists():
        raise LauncherError(MSG["env_missing"])
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    say(MSG["env_created"])


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # An activated foreign venv makes `uv run` warn; the backend has its own .venv.
    env.pop("VIRTUAL_ENV", None)
    return env


# --------------------------------------------------------------------------- prerequisites


def check_python() -> None:
    if sys.version_info < (3, 12):  # noqa: UP036 - the launcher may run on an old python
        raise LauncherError(MSG["python_old"].format(found=sys.version.split()[0]))


def find_uv() -> list[str]:
    exe = shutil.which("uv")
    if exe:
        return [exe]
    fallback = [sys.executable, "-m", "uv"]
    try:
        ok = (
            subprocess.run(
                [*fallback, "--version"], capture_output=True, timeout=20, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if ok:
        return fallback
    raise LauncherError(MSG["uv_missing"])


def find_npm() -> str:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise LauncherError(MSG["node_missing"])
    try:
        out = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=True,
        ).stdout
        version = parse_node_version(out)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise LauncherError(MSG["node_version_failed"].format(error=exc)) from exc
    if version < MIN_NODE:
        raise LauncherError(
            MSG["node_old"].format(need=f"{MIN_NODE[0]}.{MIN_NODE[1]}", found=out.strip())
        )
    return npm


def run_step(cmd: Sequence[str], cwd: Path, what: str, timeout: float | None = None) -> None:
    """Run a blocking setup command with its output shown; readable error on failure."""
    say(MSG["step_running"].format(what=what))
    try:
        result = subprocess.run(list(cmd), cwd=cwd, env=child_env(), timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise LauncherError(
            MSG["step_timeout"].format(what=what, timeout=f"{timeout:.0f}")
        ) from exc
    except OSError as exc:
        raise LauncherError(MSG["step_cannot_start"].format(what=what, error=exc)) from exc
    if result.returncode != 0:
        raise LauncherError(MSG["step_failed"].format(what=what, code=result.returncode))


def ensure_dependencies(uv: Sequence[str], npm: str) -> None:
    if needs_install(BACKEND_STAMP, [BACKEND / "uv.lock", BACKEND / "pyproject.toml"]):
        run_step([*uv, "sync"], BACKEND, MSG["step_uv_sync"], 900)
        BACKEND_STAMP.touch()
    if needs_install(FRONTEND_STAMP, [FRONTEND / "package-lock.json", FRONTEND / "package.json"]):
        run_step(
            [npm, "install", "--no-audit", "--no-fund"], FRONTEND, MSG["step_npm_install"], 900
        )
        FRONTEND_STAMP.touch()


# --------------------------------------------------------------------------- database


def tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_tcp(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if tcp_reachable(host, port):
            return True
        time.sleep(0.5)
    return False


def docker_daemon_running(docker: str) -> bool:
    try:
        return (
            subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=30,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def docker_desktop_exe() -> Path | None:
    if sys.platform != "win32":
        return None
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    exe = Path(program_files) / "Docker" / "Docker" / "Docker Desktop.exe"
    return exe if exe.exists() else None


def docker_desktop_command(exe: Path) -> list[str]:
    # `start` via a short-lived cmd: Docker Desktop's parent exits at once, so it is not in
    # the launcher's process tree and `taskkill /T` of the launcher (stop.bat) never kills it.
    return ["cmd", "/c", "start", "", str(exe)]


def launch_docker_desktop(exe: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            docker_desktop_command(exe),
            # No pipes: the started program would inherit them and run() would wait for it.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def ensure_docker_daemon(docker: str, host: str, port: int) -> None:
    """Docker daemon up, starting Docker Desktop (Windows) and waiting if needed."""
    if docker_daemon_running(docker):
        return
    exe = docker_desktop_exe()
    seconds = f"{DOCKER_START_TIMEOUT_S:.0f}"
    if exe is None:
        raise LauncherError(MSG["docker_cannot_start"].format(host=host, port=port))
    say(MSG["docker_starting"].format(seconds=seconds))
    if not launch_docker_desktop(exe):
        raise LauncherError(MSG["docker_cannot_start"].format(host=host, port=port))
    deadline = time.monotonic() + DOCKER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if docker_daemon_running(docker):
            say(MSG["docker_started"])
            return
        time.sleep(2)
    raise LauncherError(MSG["docker_timeout"].format(seconds=seconds))


def ensure_db(env: Mapping[str, str]) -> None:
    url = env.get("DATABASE_URL", "")
    if not url:
        raise LauncherError(MSG["db_url_missing"])
    try:
        host, port = parse_db_host_port(url)
    except ValueError:
        # Fixed text only: the URL (and so any exception text) may contain the password.
        raise LauncherError(MSG["db_url_invalid"]) from None

    if tcp_reachable(host, port):
        say(MSG["db_reachable"].format(host=host, port=port))
        return

    if not is_local_host(host):
        raise LauncherError(MSG["db_remote"].format(host=host, port=port))
    docker = shutil.which("docker")
    if not docker:
        raise LauncherError(MSG["db_no_docker"].format(host=host, port=port))

    ensure_docker_daemon(docker, host, port)
    run_step([docker, "compose", "up", "-d", "--wait", "db"], ROOT, MSG["step_compose_up"], 600)
    if not wait_tcp(host, port, DB_TCP_TIMEOUT_S):
        raise LauncherError(MSG["db_still_unreachable"].format(host=host, port=port))
    say(MSG["db_reachable"].format(host=host, port=port))


def migrate(uv: Sequence[str]) -> None:
    run_step([*uv, "run", "alembic", "upgrade", "head"], BACKEND, MSG["step_migrate"], 300)


# --------------------------------------------------------------------------- child processes


def port_in_use(port: int, host: str = API_HOST) -> bool:
    """True if something already listens on host:port (bind test, instant on Windows)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


@dataclass
class Child:
    name: str
    proc: subprocess.Popen[bytes]
    reader: threading.Thread = field(init=False)

    def __post_init__(self) -> None:
        self.reader = threading.Thread(target=self._pump, name=f"pump-{self.name}", daemon=True)
        self.reader.start()

    def _pump(self) -> None:
        stream: IO[bytes] | None = self.proc.stdout
        if stream is None:
            return
        prefix = f"[{self.name}] "
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            with _print_lock:
                print(prefix + line, flush=True)


def start_child(name: str, cmd: Sequence[str], cwd: Path) -> Child:
    # Own process group/session: console Ctrl+C reaches only the launcher, which then kills
    # each tree (also avoids cmd's "Terminate batch job (Y/N)?" prompt for npm.cmd).
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creationflags = 0
    try:
        proc = subprocess.Popen(
            list(cmd),
            cwd=cwd,
            env=child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=not IS_WINDOWS,
        )
    except OSError as exc:
        raise LauncherError(MSG["child_cannot_start"].format(name=name, error=exc)) from exc
    return Child(name, proc)


def _signal_group(pid: int, sig_name: str) -> None:
    """POSIX: signal a child's whole session/process group (no-op on Windows)."""
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, getattr(signal, sig_name))


def kill_tree(child: Child) -> None:
    proc = child.proc
    if IS_WINDOWS:
        # Kill the whole tree while the root still exists (uv/npm spawn python/node children).
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    else:
        _signal_group(proc.pid, "SIGTERM")
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _signal_group(proc.pid, "SIGKILL")
        proc.kill()
        proc.wait(timeout=5)


def stop_all(children: Sequence[Child]) -> None:
    if not children:
        return
    # A second Ctrl+C/Ctrl+Break must not abort cleanup and leave process trees alive.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    say(MSG["stopping"])
    for child in reversed(children):
        try:
            kill_tree(child)
        except (OSError, subprocess.SubprocessError) as exc:
            say(MSG["child_stop_failed"].format(name=child.name, pid=child.proc.pid, error=exc))
    for child in children:
        child.reader.join(timeout=2)
    say(MSG["all_stopped"])


def check_children(children: Sequence[Child]) -> None:
    for child in children:
        code = child.proc.poll()
        if code is not None:
            raise LauncherError(MSG["child_exited"].format(name=child.name, code=code))


def http_get(url: str, timeout: float = 2.0) -> tuple[int, bytes] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local http
            status: int = resp.status
            return status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError):
        return None


class Run:
    """The current launcher run: its children and the run file describing them."""

    def __init__(self) -> None:
        self.children: list[Child] = []
        self.records: list[RunRecord] = []
        self.own = make_record("launcher", os.getpid())
        if self.own is not None:
            self.records.append(self.own)
            self._write()

    def _write(self) -> None:
        if self.records:
            with contextlib.suppress(OSError):
                write_run_file(RUN_FILE, self.records)

    def add(self, child: Child) -> None:
        self.children.append(child)
        record = make_record(child.name, child.proc.pid)
        if record is not None:
            self.records.append(record)
            self._write()

    def check(self) -> None:
        """Raise if a child died or another launcher asked us to stop."""
        check_children(self.children)
        if stop_requested(self.own):
            raise StopRequested

    def close(self) -> None:
        stop_all(self.children)
        if self.own is not None and read_run_file(RUN_FILE)[:1] == [self.own]:
            remove_file(RUN_FILE)


def wait_ready(run: Run) -> str:
    """Wait for the API health endpoint and the Vite page. Returns the health status."""
    deadline = time.monotonic() + READY_TIMEOUT_S
    health_status: str | None = None
    web_ok = False
    while time.monotonic() < deadline:
        run.check()
        if health_status is None:
            res = http_get(HEALTH_URL)
            if res is not None and res[0] == 200:
                try:
                    health_status = str(json.loads(res[1]).get("status", "unknown"))
                except (ValueError, AttributeError):
                    health_status = "unknown"
        if not web_ok:
            res = http_get(WEB_URL)
            web_ok = res is not None and res[0] == 200
        if health_status is not None and web_ok:
            return health_status
        time.sleep(0.25)
    missing = []
    if health_status is None:
        missing.append(MSG["ready_missing_api"].format(url=HEALTH_URL))
    if not web_ok:
        missing.append(MSG["ready_missing_web"].format(url=WEB_URL))
    raise LauncherError(
        MSG["ready_timeout"].format(
            seconds=f"{READY_TIMEOUT_S:.0f}", missing=MSG["ready_join"].join(missing)
        )
    )


# --------------------------------------------------------------------------- main


def run_dev(open_browser: bool, started: float) -> int:
    ensure_ports_free()  # first: a running old API/UI would lock files `uv sync` replaces
    uv = find_uv()
    npm = find_npm()
    ensure_env_file()
    ensure_dependencies(uv, npm)

    run = Run()
    try:
        # The frontend does not need the DB: start it first so it boots while we migrate.
        run.add(start_child("web", [npm, "run", "dev"], FRONTEND))
        ensure_db(load_env())
        migrate(uv)
        run.check()
        api_cmd = [*uv, "run", "uvicorn", "app.main:app", "--host", API_HOST, "--port"]
        run.add(start_child("api", [*api_cmd, str(API_PORT)], BACKEND))
        run.add(start_child("worker", [*uv, "run", "python", "-m", "app.worker"], BACKEND))

        health = wait_ready(run)
        elapsed = time.monotonic() - started
        say(MSG["ready"].format(elapsed=f"{elapsed:.1f}", url=WEB_URL, health=health))
        if health != "ok":
            say(MSG["health_warning"])
        if open_browser:
            webbrowser.open(WEB_URL)
        say(MSG["press_ctrl_c"])
        while True:
            run.check()
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    except StopRequested:
        say(MSG["stop_request_received"])
        return 0
    finally:
        run.close()


def run_ensure_db() -> int:
    uv = find_uv()
    ensure_env_file()
    ensure_db(load_env())
    migrate(uv)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=MSG["help_description"])
    parser.add_argument("--no-browser", action="store_true", help=MSG["help_no_browser"])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--ensure-db", action="store_true", help=MSG["help_ensure_db"])
    modes.add_argument("--stop", action="store_true", help=MSG["help_stop"])
    args = parser.parse_args(argv)

    # A real console gets Unicode anyway (PEP 528); a pipe/file gets UTF-8 instead of ANSI.
    for stream in (sys.stdout, sys.stderr):
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")

    # Ctrl+Break (Windows) / SIGTERM (POSIX) stop cleanly like Ctrl+C, children included.
    def _interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _interrupt)
    else:
        signal.signal(signal.SIGTERM, _interrupt)

    try:
        check_python()
        if args.stop:
            return run_stop()
        if args.ensure_db:
            return run_ensure_db()
        return run_dev(open_browser=not args.no_browser, started=started)
    except LauncherError as exc:
        say(MSG["error"].format(error=exc))
        return 1
    except KeyboardInterrupt:
        say(MSG["interrupted"])
        return 130


if __name__ == "__main__":
    sys.exit(main())

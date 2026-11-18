"""MT5 terminals run in the background (M8-12): the app hides only the terminals it started.

``mark_started(exe, before)`` runs right after ``mt5.initialize``: every terminal process at
that path that was not running before the call is ours. They are kept in
``<data_dir>/mt5_terminals.json`` (PID + creation time, so a reused PID is never touched and a
worker restart keeps knowing them). A terminal the owner opened himself was running before
the call and is never recorded. ``apply_visibility`` (worker job, every few seconds) hides
the windows of our terminals, re-hiding a window the terminal restored, or shows them when
the owner chose «Показати термінали» (``<data_dir>/terminals_visible.json``).
Hidden windows have no taskbar button; the MT5 API works the same (inter-process calls).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.system.win32 import SW_HIDE, SW_SHOW, ProcessId, Win32, native

logger = logging.getLogger(__name__)

OWNED_FILE = "mt5_terminals.json"
VISIBLE_FILE = "terminals_visible.json"
_lock = threading.Lock()


@dataclass(frozen=True)
class OwnedTerminal:
    exe: str
    pid: int
    created: int
    # Windows the app hid: «Показати термінали» shows exactly these (never the terminal's
    # own hidden helper windows).
    hidden: tuple[int, ...] = ()

    @property
    def process(self) -> ProcessId:
        return ProcessId(self.pid, self.created)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read %s (%s); treated as empty", path.name, exc)
        return None


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_owned(data_dir: Path) -> list[OwnedTerminal]:
    raw = _read_json(data_dir / OWNED_FILE)
    items = raw.get("terminals") if isinstance(raw, dict) else None
    owned: list[OwnedTerminal] = []
    for item in items if isinstance(items, list) else []:
        try:
            hidden = tuple(int(h) for h in item.get("hidden", []))
            owned.append(
                OwnedTerminal(str(item["exe"]), int(item["pid"]), int(item["created"]), hidden)
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return owned


def _save_owned(data_dir: Path, owned: list[OwnedTerminal]) -> None:
    terminals = [
        {"exe": t.exe, "pid": t.pid, "created": t.created, "hidden": list(t.hidden)} for t in owned
    ]
    _write_json(data_dir / OWNED_FILE, {"terminals": terminals})


def terminals_visible(data_dir: Path) -> bool:
    """«Показати термінали»: default False (hidden)."""
    raw = _read_json(data_dir / VISIBLE_FILE)
    return isinstance(raw, dict) and raw.get("visible") is True


def set_terminals_visible(data_dir: Path, visible: bool) -> None:
    _write_json(data_dir / VISIBLE_FILE, {"visible": visible})
    logger.info("MT5 terminals: %s", "shown" if visible else "hidden")


def mark_started(win: Win32, data_dir: Path, exe: Path, before: set[ProcessId]) -> int:
    """Record the terminal processes at ``exe`` started since ``before``; returns how many."""
    new = win.processes_of(exe) - before
    if not new:
        return 0
    with _lock:
        owned = [t for t in load_owned(data_dir) if win.alive(t.process)]
        known = {t.process for t in owned}
        owned += [OwnedTerminal(str(exe), p.pid, p.created) for p in new if p not in known]
        _save_owned(data_dir, owned)
    pids = [p.pid for p in new]
    logger.info("MT5 terminal started by the app (runs hidden): %s pid=%s", exe, pids)
    apply_visibility(win, data_dir)
    return len(new)


def apply_visibility(win: Win32, data_dir: Path) -> int:
    """Hide the visible windows of our live terminals (re-hiding a restored one), or show the
    ones we hid when «Показати термінали» is on; returns windows changed."""
    visible = terminals_visible(data_dir)
    changed = 0
    with _lock:
        owned = load_owned(data_dir)
        updated: list[OwnedTerminal] = []
        for terminal in owned:
            if not win.alive(terminal.process):
                continue  # gone: drop it (its PID may be reused later)
            current = set(win.windows_of(terminal.pid))
            hidden = [h for h in terminal.hidden if h in current]
            if visible:
                for hwnd in hidden:
                    win.show(hwnd, SW_SHOW)
                    changed += 1
                hidden = []
            else:
                for hwnd in sorted(current):
                    if win.is_visible(hwnd):  # new, or one the terminal restored itself
                        win.show(hwnd, SW_HIDE)
                        changed += 1
                        if hwnd not in hidden:
                            hidden.append(hwnd)
            updated.append(
                OwnedTerminal(terminal.exe, terminal.pid, terminal.created, tuple(hidden))
            )
        if updated != owned:
            _save_owned(data_dir, updated)
    return changed


def terminal_windows(data_dir: Path) -> TerminalWindows | None:
    """The real helper on Windows, None elsewhere."""
    win = native()
    return None if win is None else TerminalWindows(win, data_dir)


class TerminalWindows:
    """What the MT5 source and the worker job use; errors are logged, never raised (hiding a
    window must never break a sync)."""

    def __init__(self, win: Win32, data_dir: Path) -> None:
        self._win = win
        self._data_dir = data_dir

    def snapshot(self, exe: Path) -> set[ProcessId]:
        try:
            return self._win.processes_of(exe)
        except OSError as exc:
            logger.warning("MT5 terminal list failed (%s); its window may stay visible", exc)
            return set()

    def started(self, exe: Path, before: set[ProcessId]) -> None:
        try:
            mark_started(self._win, self._data_dir, exe, before)
        except OSError as exc:
            logger.warning("MT5 terminal could not be hidden: %s", exc)

    def apply(self) -> None:
        try:
            apply_visibility(self._win, self._data_dir)
        except OSError as exc:
            logger.warning("MT5 terminal windows not updated: %s", exc)

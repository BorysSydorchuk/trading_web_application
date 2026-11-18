"""M8-12: MT5 terminals started by the app run with hidden windows; owner terminals untouched."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.system.terminals import (
    TerminalWindows,
    apply_visibility,
    load_owned,
    mark_started,
    set_terminals_visible,
    terminals_visible,
)
from app.system.win32 import SW_HIDE, SW_SHOW, ProcessId

EXE = Path(r"D:\MT5\fn\terminal64.exe")
OWNER = ProcessId(100, 1)  # opened by the owner before the app connected
OURS = ProcessId(200, 2)


@dataclass
class FakeWin:
    procs: set[ProcessId] = field(default_factory=set)
    windows: dict[int, list[int]] = field(default_factory=dict)
    visible: dict[int, bool] = field(default_factory=dict)
    calls: list[tuple[int, int]] = field(default_factory=list)

    def processes_of(self, exe: Path) -> set[ProcessId]:
        return set(self.procs)

    def alive(self, proc: ProcessId) -> bool:
        return proc in self.procs

    def windows_of(self, pid: int) -> list[int]:
        return list(self.windows.get(pid, []))

    def is_visible(self, hwnd: int) -> bool:
        return self.visible.get(hwnd, False)

    def show(self, hwnd: int, command: int) -> None:
        self.calls.append((hwnd, command))
        self.visible[hwnd] = command == SW_SHOW

    def start_terminal(self, proc: ProcessId, hwnds: list[int], visible: bool = True) -> None:
        self.procs.add(proc)
        self.windows[proc.pid] = hwnds
        for hwnd in hwnds:
            self.visible[hwnd] = visible


def started(win: FakeWin, data_dir: Path) -> None:
    """Owner's terminal runs; the app's initialize starts a second one."""
    win.start_terminal(OWNER, [11])
    before = win.processes_of(EXE)
    win.start_terminal(OURS, [21, 22])
    win.visible[22] = False  # a hidden helper window of the terminal itself
    assert mark_started(win, data_dir, EXE, before) == 1


def test_only_the_terminal_started_by_the_app_is_recorded_and_hidden(tmp_path: Path) -> None:
    win = FakeWin()
    started(win, tmp_path)

    owned = load_owned(tmp_path)
    assert [(t.pid, t.created, t.hidden) for t in owned] == [(200, 2, (21,))]
    assert win.calls == [(21, SW_HIDE)]
    assert win.visible[11] is True  # the owner's terminal is never touched


def test_a_restored_window_is_hidden_again(tmp_path: Path) -> None:
    win = FakeWin()
    started(win, tmp_path)
    win.visible[21] = True  # the terminal restored itself

    assert apply_visibility(win, tmp_path) == 1
    assert win.visible[21] is False
    assert apply_visibility(win, tmp_path) == 0  # nothing to do the next round


def test_show_restores_exactly_the_windows_the_app_hid(tmp_path: Path) -> None:
    win = FakeWin()
    started(win, tmp_path)

    set_terminals_visible(tmp_path, True)
    apply_visibility(win, tmp_path)

    assert terminals_visible(tmp_path) is True
    assert win.visible[21] is True
    assert win.visible[22] is False  # the terminal's own hidden window stays hidden
    assert load_owned(tmp_path)[0].hidden == ()

    set_terminals_visible(tmp_path, False)
    apply_visibility(win, tmp_path)
    assert win.visible[21] is False


def test_an_exited_terminal_is_dropped_and_a_reused_pid_is_never_touched(tmp_path: Path) -> None:
    win = FakeWin()
    started(win, tmp_path)
    win.procs.discard(OURS)
    win.start_terminal(ProcessId(200, 99), [31])  # same PID, another process

    apply_visibility(win, tmp_path)

    assert load_owned(tmp_path) == []
    assert win.visible[31] is True


def test_the_record_survives_a_worker_restart(tmp_path: Path) -> None:
    win = FakeWin()
    started(win, tmp_path)
    win.visible[21] = True

    TerminalWindows(win, tmp_path).apply()  # a new helper reads the stored PIDs

    assert win.visible[21] is False


def test_defaults_and_a_broken_file_mean_hidden_and_none_owned(tmp_path: Path) -> None:
    assert terminals_visible(tmp_path) is False
    (tmp_path / "mt5_terminals.json").write_text("{broken", encoding="utf-8")
    assert load_owned(tmp_path) == []


def test_helper_errors_never_escape(tmp_path: Path) -> None:
    class Broken(FakeWin):
        def processes_of(self, exe: Path) -> set[ProcessId]:
            raise OSError("access denied")

    helper = TerminalWindows(Broken(), tmp_path)
    assert helper.snapshot(EXE) == set()
    helper.started(EXE, set())  # logged, not raised

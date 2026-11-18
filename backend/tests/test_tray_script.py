"""M8-12: scripts/tray.py helpers and scripts/install_shortcuts.py (no real tray, no shell)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.system import shortcuts

ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"tj_{name}", ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tray = load("tray")
installer = load("install_shortcuts")


def test_launcher_runs_dev_py_without_its_browser() -> None:
    cmd = tray.launcher_command(Path("python.exe"), "--no-browser")
    assert cmd == ["python.exe", str(ROOT / "scripts" / "dev.py"), "--no-browser"]


def test_rotate_log_keeps_one_previous_copy(tmp_path: Path) -> None:
    log = tmp_path / "launcher.log"
    log.write_bytes(b"x" * 20)

    tray.rotate_log(log, max_bytes=10)

    assert not log.exists()
    assert (tmp_path / "launcher.log.1").read_bytes() == b"x" * 20
    tray.rotate_log(log, max_bytes=10)  # missing file: nothing to do


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console flags")
def test_children_get_a_new_console_that_is_never_shown() -> None:
    kwargs = tray.hidden_console()
    assert kwargs["creationflags"] == tray.CREATE_NEW_CONSOLE
    info: subprocess.STARTUPINFO = kwargs["startupinfo"]
    assert info.dwFlags & tray.STARTF_USESHOWWINDOW
    assert info.wShowWindow == tray.SW_HIDE


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcuts")
def test_installer_writes_both_desktop_shortcuts_and_autostart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop, startup = tmp_path / "Desktop", tmp_path / "Startup"
    desktop.mkdir()
    startup.mkdir()
    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_bytes(b"")
    monkeypatch.setattr(shortcuts, "PYTHONW", pythonw)
    monkeypatch.setattr(shortcuts, "ICON_FILE", tmp_path / "journal.ico")
    monkeypatch.setattr(shortcuts, "desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcuts, "startup_dir", lambda: startup)

    def shell(args: list[str], env: dict[str, str]) -> None:
        Path(env["TJ_LNK"]).write_bytes(b"lnk")

    lines = installer.install(autostart=True, runner=shell)

    assert sorted(p.name for p in desktop.iterdir()) == [shortcuts.START_NAME, shortcuts.STOP_NAME]
    assert (startup / shortcuts.AUTOSTART_NAME).is_file()
    assert (tmp_path / "journal.ico").stat().st_size > 0
    assert lines[-1] == "Автозапуск з Windows: увімкнено"

    installer.install(autostart=False, runner=shell)  # run again: repairs, removes autostart
    assert not (startup / shortcuts.AUTOSTART_NAME).exists()
    assert len(list(desktop.iterdir())) == 2


def test_installer_needs_the_backend_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortcuts, "PYTHONW", tmp_path / "missing.exe")
    with pytest.raises(shortcuts.ShortcutError, match=r"start\.bat"):
        installer.install(autostart=True, runner=lambda a, e: None)

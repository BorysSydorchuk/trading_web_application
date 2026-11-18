"""Desktop shortcuts «Торговий журнал — Старт / Стоп» and autostart at Windows login (M8-12).

All three run ``backend/.venv/Scripts/pythonw.exe scripts/tray.py`` (no console window):
Start = tray + app + open the journal, Stop = stop the app, Startup (autostart) = tray + app
without opening the browser. Autostart is a shortcut in the user's Startup folder (no admin
rights, no Task Scheduler). Shortcuts are written through the Windows Script Host COM object
(``WScript.Shell``) from a hidden PowerShell; values travel as environment variables, so no
path is ever quoted into a script. Creating twice just rewrites the same file (idempotent).
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT

logger = logging.getLogger(__name__)

PYTHONW = REPO_ROOT / "backend" / ".venv" / "Scripts" / "pythonw.exe"
TRAY_SCRIPT = REPO_ROOT / "scripts" / "tray.py"
ICON_FILE = REPO_ROOT / "data" / "journal.ico"

START_NAME = "Торговий журнал — Старт.lnk"
STOP_NAME = "Торговий журнал — Стоп.lnk"
AUTOSTART_NAME = "Торговий журнал.lnk"

_CSIDL_DESKTOPDIRECTORY = 0x0010
_CSIDL_STARTUP = 0x0007
_CREATE_NO_WINDOW = 0x08000000
_PS_SCRIPT = (
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TJ_LNK);"
    "$s.TargetPath=$env:TJ_TARGET;$s.Arguments=$env:TJ_ARGS;"
    "$s.WorkingDirectory=$env:TJ_WORKDIR;$s.IconLocation=$env:TJ_ICON;"
    "$s.Description=$env:TJ_DESC;$s.Save()"
)


class ShortcutError(Exception):
    """A shortcut could not be written or removed (message is shown to the owner)."""


@dataclass(frozen=True)
class Shortcut:
    path: Path
    arguments: str
    description: str


Runner = Callable[[list[str], dict[str, str]], None]


def _known_folder(csidl: int) -> Path:
    if sys.platform != "win32":
        raise ShortcutError("Windows only")
    buf = ctypes.create_unicode_buffer(260)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    if result != 0 or not buf.value:
        raise ShortcutError(f"Windows folder {csidl:#x} not found (code {result})")
    return Path(buf.value)


def desktop_dir() -> Path:
    return _known_folder(_CSIDL_DESKTOPDIRECTORY)


def startup_dir() -> Path:
    return _known_folder(_CSIDL_STARTUP)


def start_shortcut(desktop: Path) -> Shortcut:
    return Shortcut(desktop / START_NAME, "", "Запустити торговий журнал")


def stop_shortcut(desktop: Path) -> Shortcut:
    return Shortcut(desktop / STOP_NAME, "--stop", "Зупинити торговий журнал")


def autostart_shortcut(startup: Path) -> Shortcut:
    return Shortcut(startup / AUTOSTART_NAME, "--autostart", "Торговий журнал: запуск з Windows")


def _run_powershell(args: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603 (fixed powershell command, values via env)
        args,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )
    if result.returncode != 0:
        raise ShortcutError(result.stderr.strip() or f"powershell exit {result.returncode}")


def write_shortcut(shortcut: Shortcut, run: Runner = _run_powershell) -> None:
    """Create or overwrite ``shortcut`` (target pythonw + tray.py, the app icon)."""
    tray = f'"{TRAY_SCRIPT}"'
    env = os.environ | {
        "TJ_LNK": str(shortcut.path),
        "TJ_TARGET": str(PYTHONW),
        "TJ_ARGS": f"{tray} {shortcut.arguments}".strip(),
        "TJ_WORKDIR": str(REPO_ROOT),
        "TJ_ICON": str(ICON_FILE),
        "TJ_DESC": shortcut.description,
    }
    command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT]
    try:
        run(command, env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShortcutError(str(exc)) from exc
    logger.info("Shortcut written: %s", shortcut.path)


def remove_shortcut(shortcut: Shortcut) -> None:
    try:
        shortcut.path.unlink(missing_ok=True)
    except OSError as exc:
        raise ShortcutError(str(exc)) from exc
    logger.info("Shortcut removed: %s", shortcut.path)


def autostart_enabled(startup: Path | None = None) -> bool:
    return autostart_shortcut(startup or startup_dir()).path.is_file()


def set_autostart(
    enabled: bool, startup: Path | None = None, run: Runner = _run_powershell
) -> None:
    """«Запускати з Windows»: add or remove the Startup-folder shortcut."""
    shortcut = autostart_shortcut(startup or startup_dir())
    if enabled:
        write_shortcut(shortcut, run)
    else:
        remove_shortcut(shortcut)

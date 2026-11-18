# ruff: noqa: S603, RUF001
# S603: only our own scripts with fixed arguments; RUF001: Ukrainian tray messages on purpose.
"""Trading Journal in the background with a tray icon (M8-12). Runs under pythonw (no console).

    backend/.venv/Scripts/pythonw.exe scripts/tray.py              start, open the journal
    backend/.venv/Scripts/pythonw.exe scripts/tray.py --autostart  start at login, no browser
    backend/.venv/Scripts/pythonw.exe scripts/tray.py --stop       stop the app

The tray starts ``scripts/dev.py --no-browser`` with CREATE_NO_WINDOW: it gets a console
without a window, and every child (uv, npm, uvicorn, the worker) inherits it, so no window
appears (also with Windows Terminal as the default terminal). Launcher output goes to
``logs/launcher.log``, the tray's own messages to ``logs/tray.log``. A failed start, a crash
or an incomplete stop shows a Windows notification («Відкрийте «Логи»»); a tray that cannot
start at all shows a message box. One tray per user (named mutex): a second «Старт» only opens
the journal. «Стоп» (shortcut or menu) leaves a stop flag for the tray, so its launcher exit
is never reported as a crash. Shortcuts and autostart: ``scripts/install_shortcuts.py``.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

LOG_DIR = ROOT / "logs"
LAUNCHER_LOG = LOG_DIR / "launcher.log"
TRAY_LOG = LOG_DIR / "tray.log"
STOP_FLAG = ROOT / "data" / "tray_stop.flag"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"
WEB_URL = "http://127.0.0.1:5173/"
HEALTH_URL = "http://127.0.0.1:8000/api/health"
MUTEX_NAME = "Local\\TradingJournalTray"
MAX_LOG_BYTES = 5 * 1024 * 1024
READY_TIMEOUT_S = 600
STOP_TIMEOUT_S = 120
ERROR_ALREADY_EXISTS = 183
CREATE_NO_WINDOW = 0x08000000

MSG = {
    "title": "Торговий журнал",
    "title_running": "Торговий журнал — працює",
    "title_starting": "Торговий журнал — запуск…",
    "title_failed": "Торговий журнал — помилка, див. «Логи»",
    "open": "Відкрити журнал",
    "show_terminals": "Показати термінали",
    "hide_terminals": "Сховати термінали",
    "logs": "Логи",
    "autostart": "Запускати з Windows",
    "restart": "Запустити знову",
    "stop": "Зупинити",
    "ready": "Журнал працює у фоні. Значок — в області сповіщень.",
    "failed": "Журнал зупинився з помилкою (код {code}). Відкрийте «Логи» (launcher.log).",
    "start_failed": "Не вдалося запустити журнал: {error}. Відкрийте «Логи».",
    "timeout": "Журнал не запустився за {minutes} хв. Відкрийте «Логи» (launcher.log).",
    "autostart_failed": "Не вдалося змінити автозапуск: {error}",
    "stop_incomplete": "Не всі процеси журналу зупинились. Відкрийте «Логи» (launcher.log).",
    "fatal": "Торговий журнал не запустився:\n{error}\n\nПодробиці: {log}",
}

logger = logging.getLogger("tray")

try:  # the tray must show a message box even when the backend venv is incomplete
    from app.config import get_settings
    from app.system import shortcuts
    from app.system.icon import draw_icon, write_icon
    from app.system.terminals import set_terminals_visible, terminals_visible

    IMPORT_ERROR: Exception | None = None
except Exception as exc:
    IMPORT_ERROR = exc


# --------------------------------------------------------------------------- pure helpers


def venv_python() -> Path:
    """python.exe next to the running pythonw.exe (the backend venv)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("python.exe")
    return candidate if candidate.is_file() else exe


def launcher_command(python: Path, *extra: str) -> list[str]:
    return [str(python), str(DEV_SCRIPT), *extra]


def rotate_log(path: Path, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Keep one previous copy (``.1``) once the log passes ``max_bytes``.

    A log another process holds open cannot be renamed on Windows: keep appending.
    """
    try:
        if path.stat().st_size > max_bytes:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Log %s not rotated (%s); appending", path.name, exc)


def hidden_console() -> dict[str, Any]:
    """Popen kwargs: a console without a window (children inherit it)."""
    return {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def is_up(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (localhost)
            return 200 <= int(response.status) < 300
    except OSError:
        return False


_mutex_handle: int | None = None


def single_instance() -> bool:
    """True for the first tray of this user (keeps a named mutex for the process lifetime)."""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    _mutex_handle = handle
    return True


def request_tray_stop() -> None:
    """Tell a running tray that the next launcher exit is a requested stop."""
    STOP_FLAG.parent.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.write_text("stop", encoding="utf-8")


def take_tray_stop() -> bool:
    try:
        STOP_FLAG.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Stop flag not removed: %s", exc)
    return True


def run_stop() -> int:
    """Flag the stop for the tray, then `dev.py --stop` without a window; its exit code."""
    request_tray_stop()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LAUNCHER_LOG.open("ab") as log:
        proc = subprocess.Popen(
            launcher_command(venv_python(), "--stop"),
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **hidden_console(),
        )
        try:
            return proc.wait(timeout=STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            logger.error("dev.py --stop did not finish in %s s", STOP_TIMEOUT_S)
            return 1


def kill_tree(pid: int) -> None:
    """Last resort after a stop: the launcher tree is still alive (e.g. before its run file)."""
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],  # noqa: S607 (Windows system tool)
        capture_output=True,
        timeout=30,
        check=False,
        **hidden_console(),
    )


class Action(Enum):
    WAIT = "wait"
    READY = "ready"
    QUIT = "quit"  # requested stop, or a clean launcher exit
    FAILED = "failed"  # launcher exited with an error
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class Tick:
    exit_code: int | None  # None = launcher still running
    stop_requested: bool
    ready: bool  # already reported ready
    up: bool  # health + web answer now
    waited_s: float  # since this launch
    timeout_reported: bool


def decide(tick: Tick, timeout_s: float = READY_TIMEOUT_S) -> Action:
    """What the watch loop does this second (pure, tested)."""
    if tick.stop_requested:
        return Action.QUIT
    if tick.exit_code is not None:
        return Action.QUIT if tick.exit_code == 0 else Action.FAILED
    if tick.ready:
        return Action.WAIT
    if tick.up:
        return Action.READY
    if tick.waited_s > timeout_s and not tick.timeout_reported:
        return Action.TIMEOUT
    return Action.WAIT


# --------------------------------------------------------------------------- tray app


class TrayApp:
    def __init__(self, open_browser: bool) -> None:
        import pystray

        self._pystray = pystray
        self._open_browser = open_browser
        self._data_dir = get_settings().data_dir
        self._proc: subprocess.Popen[bytes] | None = None
        self._log: IO[bytes] | None = None
        self._lock = threading.Lock()
        self._ready = False
        self._started_at = time.monotonic()
        self._timeout_reported = False
        self.icon = pystray.Icon(
            "trading_journal", draw_icon(64), MSG["title_starting"], self._menu()
        )

    def _menu(self) -> Any:
        item = self._pystray.MenuItem
        return self._pystray.Menu(
            item(MSG["open"], lambda: webbrowser.open(WEB_URL), default=True),
            item(self._terminals_label, self._toggle_terminals),
            item(MSG["logs"], lambda: os.startfile(LOG_DIR)),  # noqa: S606 (own folder)
            item(MSG["autostart"], self._toggle_autostart, checked=lambda _: self._autostart()),
            item(MSG["restart"], self._restart, visible=lambda _: not self._running()),
            item(MSG["stop"], self._stop_async),
        )

    def _notify(self, text: str, title: str | None = None) -> None:
        if title is not None:
            self.icon.title = title
        try:
            self.icon.notify(text, MSG["title"])
        except Exception:  # a notification must never kill the tray
            logger.exception("Notification failed: %s", text)

    # -- menu actions

    def _terminals_label(self, _: Any) -> str:
        return MSG["hide_terminals"] if terminals_visible(self._data_dir) else MSG["show_terminals"]

    def _toggle_terminals(self) -> None:
        set_terminals_visible(self._data_dir, not terminals_visible(self._data_dir))

    def _autostart(self) -> bool:
        try:
            return shortcuts.autostart_enabled()
        except shortcuts.ShortcutError:
            return False

    def _toggle_autostart(self) -> None:
        try:
            shortcuts.set_autostart(not self._autostart())
        except shortcuts.ShortcutError as exc:
            logger.error("Autostart change failed: %s", exc)
            self._notify(MSG["autostart_failed"].format(error=exc))

    def _restart(self) -> None:
        if not self._running():
            self._start_launcher()

    def _stop_async(self) -> None:
        threading.Thread(target=self._stop, name="tray-stop", daemon=True).start()

    def _stop(self) -> None:
        """«Зупинити»: same path as the desktop «Стоп»; the watch loop closes the tray."""
        code = run_stop()
        logger.info("Stop requested from the tray, dev.py --stop exit %s", code)
        if code != 0:
            self._notify(MSG["stop_incomplete"])

    # -- launcher

    def _running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start_launcher(self) -> None:
        with self._lock:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            rotate_log(LAUNCHER_LOG)
            if self._log is not None:
                self._log.close()
            self._log = LAUNCHER_LOG.open("ab")
            self._ready = False
            self._timeout_reported = False
            self._started_at = time.monotonic()
            self.icon.title = MSG["title_starting"]
            try:
                self._proc = subprocess.Popen(
                    launcher_command(venv_python(), "--no-browser"),
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=self._log,
                    stderr=subprocess.STDOUT,
                    **hidden_console(),
                )
            except OSError as exc:
                logger.error("Launcher could not start: %s", exc)
                self._notify(MSG["start_failed"].format(error=exc), MSG["title_failed"])
                return
            logger.info("Launcher started, pid %s", self._proc.pid)

    def _on_ready(self) -> None:
        self._ready = True
        self.icon.title = MSG["title_running"]
        logger.info("App is ready")
        if self._open_browser:
            webbrowser.open(WEB_URL)
            self._open_browser = False
        else:
            self._notify(MSG["ready"])

    def _quit(self, proc: subprocess.Popen[bytes] | None) -> None:
        if proc is not None:
            try:
                proc.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                logger.warning("Launcher still alive after the stop: killing its tree")
                kill_tree(proc.pid)
        logger.info("Tray exits")
        self.icon.stop()

    def _watch(self) -> None:
        while True:
            proc = self._proc
            code = proc.poll() if proc is not None else None
            stop = take_tray_stop()
            running = proc is not None and code is None
            tick = Tick(
                exit_code=code,
                stop_requested=stop,
                ready=self._ready or not running,
                up=running and not self._ready and is_up(HEALTH_URL) and is_up(WEB_URL),
                waited_s=time.monotonic() - self._started_at,
                timeout_reported=self._timeout_reported or not running,
            )
            action = decide(tick)
            if action is Action.QUIT:
                self._quit(proc if running else None)
                return
            if action is Action.FAILED:
                logger.error("Launcher exited with code %s", code)
                self._proc = None
                self._notify(MSG["failed"].format(code=code), MSG["title_failed"])
            elif action is Action.READY:
                self._on_ready()
            elif action is Action.TIMEOUT:
                self._timeout_reported = True
                text = MSG["timeout"].format(minutes=READY_TIMEOUT_S // 60)
                self._notify(text, MSG["title_failed"])
            time.sleep(1)

    def run(self) -> None:
        def setup(icon: Any) -> None:
            try:
                icon.visible = True
                take_tray_stop()  # a stale flag from an earlier «Стоп» must not stop this run
                self._start_launcher()
                threading.Thread(target=self._watch, name="tray-watch", daemon=True).start()
            except Exception as exc:
                logger.exception("Tray setup failed")
                self._notify(MSG["start_failed"].format(error=exc), MSG["title_failed"])

        self.icon.run(setup=setup)
        if self._log is not None:
            self._log.close()


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rotate_log(TRAY_LOG)
    logging.basicConfig(
        filename=TRAY_LOG,
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def show_fatal(error: object) -> None:
    """A tray that cannot start at all: a message box (errors must be visible)."""
    text = MSG["fatal"].format(error=error, log=TRAY_LOG)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, text, MSG["title"], 0x10)  # MB_ICONERROR
    else:
        print(text, file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trading Journal tray")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--autostart", action="store_true", help="start at login, no browser")
    mode.add_argument("--stop", action="store_true", help="stop the app")
    args = parser.parse_args(argv)
    try:
        configure_logging()
    except OSError as exc:
        show_fatal(exc)
        return 1
    if IMPORT_ERROR is not None:
        logger.error("Backend modules not importable: %s", IMPORT_ERROR)
        show_fatal(IMPORT_ERROR)
        return 1
    try:
        return _run(args.stop, args.autostart)
    except Exception as exc:
        logger.exception("Tray failed")
        show_fatal(exc)
        return 1


def _run(stop: bool, autostart: bool) -> int:
    if stop:
        code = run_stop()  # the running tray sees the stop flag and closes itself
        logger.info("Stop shortcut: dev.py --stop exit %s", code)
        if code != 0:
            show_fatal(MSG["stop_incomplete"])
        return code
    if not shortcuts.ICON_FILE.is_file():
        write_icon(shortcuts.ICON_FILE)
    if not single_instance():
        logger.info("Tray already running: opening the journal only")
        if not autostart:
            webbrowser.open(WEB_URL)
        return 0
    TrayApp(open_browser=not autostart).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

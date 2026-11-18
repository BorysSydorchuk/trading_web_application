"""Trading Journal in the background with a tray icon (M8-12). Runs under pythonw (no console).

    backend/.venv/Scripts/pythonw.exe scripts/tray.py              start, open the journal
    backend/.venv/Scripts/pythonw.exe scripts/tray.py --autostart  start at login, no browser
    backend/.venv/Scripts/pythonw.exe scripts/tray.py --stop       stop the app

The tray starts ``scripts/dev.py --no-browser`` in its own hidden console: every child (uv,
npm, uvicorn, the worker) inherits that hidden console, so no window appears. Launcher output
goes to ``logs/launcher.log``, the tray's own messages to ``logs/tray.log``. A failed start or a
crash shows a Windows notification («Відкрийте «Логи»»). One tray per user (named mutex): a
second «Старт» only opens the journal. The desktop shortcuts and autostart are made by
``scripts/install_shortcuts.py``.
"""

# ruff: noqa: S603, RUF001
# S603: only our own scripts with fixed arguments; RUF001: Ukrainian tray messages on purpose.
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.system import shortcuts  # noqa: E402
from app.system.icon import draw_icon, write_icon  # noqa: E402
from app.system.terminals import set_terminals_visible, terminals_visible  # noqa: E402

LOG_DIR = ROOT / "logs"
LAUNCHER_LOG = LOG_DIR / "launcher.log"
TRAY_LOG = LOG_DIR / "tray.log"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"
WEB_URL = "http://127.0.0.1:5173/"
HEALTH_URL = "http://127.0.0.1:8000/api/health"
MUTEX_NAME = "Local\\TradingJournalTray"
MAX_LOG_BYTES = 5 * 1024 * 1024
READY_TIMEOUT_S = 600
STOP_TIMEOUT_S = 120

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0

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
}

logger = logging.getLogger("tray")


# --------------------------------------------------------------------------- pure helpers


def venv_python() -> Path:
    """python.exe next to the running pythonw.exe (the backend venv)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("python.exe")
    return candidate if candidate.is_file() else exe


def launcher_command(python: Path, *extra: str) -> list[str]:
    return [str(python), str(DEV_SCRIPT), *extra]


def rotate_log(path: Path, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Keep one previous copy (``.1``) once the log passes ``max_bytes``."""
    try:
        if path.stat().st_size > max_bytes:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except FileNotFoundError:
        return


def hidden_console() -> dict[str, Any]:
    """Popen kwargs: a new console that is never shown (children inherit it)."""
    if sys.platform != "win32":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= STARTF_USESHOWWINDOW
    info.wShowWindow = SW_HIDE
    return {"creationflags": CREATE_NEW_CONSOLE, "startupinfo": info}


def is_up(url: str, timeout: float = 2.0) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (localhost)
            return 200 <= int(response.status) < 300
    except OSError:
        return False


def single_instance() -> object | None:
    """Named mutex handle, or None when another tray already runs."""
    if sys.platform != "win32":
        return object()
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    return None if already else handle


def run_stop() -> int:
    """`dev.py --stop` in a hidden console; returns its exit code."""
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


# --------------------------------------------------------------------------- tray app


class TrayApp:
    def __init__(self, open_browser: bool) -> None:
        import pystray

        self._pystray = pystray
        self._open_browser = open_browser
        self._data_dir = get_settings().data_dir
        self._proc: subprocess.Popen[bytes] | None = None
        self._log: IO[bytes] | None = None
        self._stopping = threading.Event()
        self._ready = False
        self.icon = pystray.Icon(
            "trading_journal", draw_icon(64), MSG["title_starting"], self._menu()
        )

    def _menu(self) -> Any:
        item = self._pystray.MenuItem
        return self._pystray.Menu(
            item(MSG["open"], lambda: webbrowser.open(WEB_URL), default=True),
            item(
                lambda _: (
                    MSG["hide_terminals"] if self._terminals_shown() else MSG["show_terminals"]
                ),
                self._toggle_terminals,
            ),
            item(MSG["logs"], lambda: os.startfile(LOG_DIR)),  # noqa: S606 (own folder)
            item(MSG["autostart"], self._toggle_autostart, checked=lambda _: self._autostart()),
            item(MSG["restart"], self._restart, visible=lambda _: not self._running()),
            item(MSG["stop"], self._stop),
        )

    # -- menu actions

    def _terminals_label(self, _: Any) -> str:
        return MSG["hide_terminals"] if self._terminals_shown() else MSG["show_terminals"]

    def _terminals_shown(self) -> bool:
        return terminals_visible(self._data_dir)

    def _toggle_terminals(self) -> None:
        set_terminals_visible(self._data_dir, not self._terminals_shown())

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
            self.icon.notify(MSG["autostart_failed"].format(error=exc), MSG["title"])

    def _restart(self) -> None:
        if not self._running():
            self._start_launcher()

    def _stop(self) -> None:
        self._stopping.set()
        code = run_stop()
        logger.info("Stop requested from the tray, dev.py --stop exit %s", code)
        self.icon.stop()

    # -- launcher

    def _running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start_launcher(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rotate_log(LAUNCHER_LOG)
        if self._log is not None:
            self._log.close()
        self._log = LAUNCHER_LOG.open("ab")
        self._ready = False
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
            self.icon.title = MSG["title_failed"]
            self.icon.notify(MSG["start_failed"].format(error=exc), MSG["title"])
            return
        logger.info("Launcher started, pid %s", self._proc.pid)

    def _watch(self) -> None:
        """Ready -> notify (and open the journal); exit -> quit (stop) or notify (error)."""
        started = time.monotonic()
        while not self._stopping.is_set():
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                code = proc.returncode
                self._proc = None
                if code == 0:
                    logger.info("Launcher stopped (exit 0): tray exits")
                    self.icon.stop()
                    return
                logger.error("Launcher exited with code %s", code)
                self.icon.title = MSG["title_failed"]
                self.icon.notify(MSG["failed"].format(code=code), MSG["title"])
            elif proc is not None and not self._ready:
                if is_up(HEALTH_URL) and is_up(WEB_URL):
                    self._ready = True
                    self.icon.title = MSG["title_running"]
                    logger.info("App is ready")
                    if self._open_browser:
                        webbrowser.open(WEB_URL)
                        self._open_browser = False
                    else:
                        self.icon.notify(MSG["ready"], MSG["title"])
                elif time.monotonic() - started > READY_TIMEOUT_S:
                    started = float("inf")  # notify once
                    self.icon.title = MSG["title_failed"]
                    self.icon.notify(
                        MSG["timeout"].format(minutes=READY_TIMEOUT_S // 60), MSG["title"]
                    )
            time.sleep(1)

    def run(self) -> None:
        def setup(icon: Any) -> None:
            icon.visible = True
            self._start_launcher()
            threading.Thread(target=self._watch, name="tray-watch", daemon=True).start()

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trading Journal tray")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--autostart", action="store_true", help="start at login, no browser")
    mode.add_argument("--stop", action="store_true", help="stop the app")
    args = parser.parse_args(argv)
    configure_logging()
    if args.stop:
        code = run_stop()  # the running tray sees its launcher exit 0 and closes itself
        logger.info("Stop shortcut: dev.py --stop exit %s", code)
        return code
    if not shortcuts.ICON_FILE.is_file():
        write_icon(shortcuts.ICON_FILE)
    mutex = single_instance()
    if mutex is None:
        logger.info("Tray already running: opening the journal only")
        if not args.autostart:
            webbrowser.open(WEB_URL)
        return 0
    try:
        TrayApp(open_browser=not args.autostart).run()
    except Exception:
        logger.exception("Tray crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

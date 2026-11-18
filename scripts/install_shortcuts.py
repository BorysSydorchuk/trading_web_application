"""Create or repair the desktop shortcuts and autostart (M8-12). Safe to run again.

    uv run --project backend python scripts/install_shortcuts.py [--no-autostart]

Desktop: «Торговий журнал — Старт» and «Торговий журнал — Стоп» (app icon, no console).
Autostart at Windows login: ON by default (owner decision 2026-11-18); ``--no-autostart``
removes it. The same switch is in Settings and in the tray menu («Запускати з Windows»).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.system import shortcuts
from app.system.icon import write_icon


def install(autostart: bool, runner: shortcuts.Runner | None = None) -> list[str]:
    """Write the icon and all shortcuts; returns one Ukrainian line per step."""
    run = runner or shortcuts._run_powershell
    lines: list[str] = []
    if not shortcuts.PYTHONW.is_file():
        raise shortcuts.ShortcutError(
            f"немає {shortcuts.PYTHONW}: спершу запустіть start.bat (встановлює залежності)"
        )
    write_icon(shortcuts.ICON_FILE)
    desktop = shortcuts.desktop_dir()
    for shortcut in (shortcuts.start_shortcut(desktop), shortcuts.stop_shortcut(desktop)):
        shortcuts.write_shortcut(shortcut, run)
        lines.append(f"Ярлик: {shortcut.path}")
    shortcuts.set_autostart(autostart, run=run)
    lines.append(
        "Автозапуск з Windows: увімкнено" if autostart else "Автозапуск з Windows: вимкнено"
    )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trading Journal shortcuts and autostart")
    parser.add_argument("--no-autostart", action="store_true", help="do not start with Windows")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("[shortcuts] Лише для Windows.")
        return 1
    try:
        for line in install(autostart=not args.no_autostart):
            print(f"[shortcuts] {line}")
    except shortcuts.ShortcutError as exc:
        print(f"[shortcuts] Помилка: {exc}")
        return 1
    print("[shortcuts] Готово. Запуск: ярлик «Торговий журнал — Старт» на робочому столі.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

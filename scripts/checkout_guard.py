"""Startup guard: warn before the app runs from anything but a clean ``main`` (owner 2026-11-23).

The app once ran from an unmerged branch, which hid work already merged into main. start.bat,
the tray and autostart ask for confirmation; the default answer is to abort. Standard library
only: scripts/dev.py runs before the backend environment exists.
"""

# Fixed git commands; Ukrainian text (Cyrillic look-alike letters are intended).
# ruff: noqa: S603, S607, RUF001

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

MAIN_BRANCH = "main"
# Set for a launcher whose start was already confirmed (tray) or is a QA run on a branch.
ACCEPT_ENV = "TJ_ACCEPT_CHECKOUT"
GIT_TIMEOUT_S = 10
CREATE_NO_WINDOW = 0x08000000
YES_ANSWERS = frozenset({"т", "так", "y", "yes"})

PROMPT = "Запустити все одно? [т/Н]: "
ABORTED = "Запуск скасовано. Перейдіть на main: git switch main"
UNKNOWN = "[start] Увага: не вдалося перевірити гілку git. Запускаю без перевірки."


@dataclass(frozen=True)
class Checkout:
    branch: str  # "HEAD" when detached
    changed_files: int

    @property
    def is_clean_main(self) -> bool:
        return self.branch == MAIN_BRANCH and self.changed_files == 0


def _git(root: Path, *args: str) -> str:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_S,
        check=True,
        creationflags=flags,
    ).stdout


def read_checkout(root: Path) -> Checkout | None:
    """Current branch and changed files; None when git cannot answer."""
    try:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        status = _git(root, "status", "--porcelain")
    except (OSError, subprocess.SubprocessError):
        return None
    return Checkout(branch, sum(1 for line in status.splitlines() if line.strip()))


def warning_text(state: Checkout) -> str:
    lines = ["Увага: застосунок запускається не з чистої гілки main."]
    if state.branch != MAIN_BRANCH:
        shown = "відокремлений HEAD" if state.branch == "HEAD" else state.branch
        lines.append(f"Поточна гілка: {shown}. Злиті в main зміни можуть бути не видні.")
    if state.changed_files:
        lines.append(f"Незакомічені зміни: файлів {state.changed_files}.")
    return "\n".join(lines)


def is_yes(answer: str) -> bool:
    return answer.strip().lower() in YES_ANSWERS


def confirm_console(
    root: Path,
    env: Mapping[str, str],
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> bool:
    """True when the start may go on. No answer (no console, empty, anything else) aborts."""
    if env.get(ACCEPT_ENV) == "1":
        return True
    state = read_checkout(root)
    if state is None:
        say(UNKNOWN)
        return True
    if state.is_clean_main:
        return True
    say(warning_text(state))
    try:
        accepted = is_yes(ask(PROMPT))
    except EOFError:
        accepted = False
    if not accepted:
        say(ABORTED)
    return accepted

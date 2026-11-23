"""Startup guard: anything but a clean main needs an explicit yes; the default is to abort."""

# Fixed git commands in a temporary repository.
# ruff: noqa: S603, S607, RUF001

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "checkout_guard.py"
    spec = importlib.util.spec_from_file_location("tj_checkout_guard", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load()


def _state(monkeypatch: pytest.MonkeyPatch, branch: str, changed: int) -> None:
    paths = tuple(f"f{i}.py" for i in range(changed))
    monkeypatch.setattr(guard, "read_checkout", lambda _root: guard.Checkout(branch, paths))


def _confirm(answer: str | None, env: dict[str, str] | None = None) -> tuple[bool, list[str]]:
    said: list[str] = []

    def ask(_prompt: str) -> str:
        if answer is None:
            raise EOFError
        return answer

    return guard.confirm_console(ROOT, env or {}, ask=ask, say=said.append), said


def test_clean_main_starts_without_a_question(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch, "main", 0)
    assert _confirm(None) == (True, [])


@pytest.mark.parametrize(("branch", "changed"), [("fix/x", 0), ("main", 2), ("HEAD", 0)])
@pytest.mark.parametrize("answer", ["", "н", "no", "щось", None])
def test_default_answer_aborts(
    monkeypatch: pytest.MonkeyPatch, branch: str, changed: int, answer: str | None
) -> None:
    _state(monkeypatch, branch, changed)
    accepted, said = _confirm(answer)
    assert accepted is False
    assert said[-1] == guard.ABORTED


@pytest.mark.parametrize("answer", ["т", "Так", " y ", "YES"])
def test_explicit_yes_continues(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    _state(monkeypatch, "fix/x", 1)
    accepted, said = _confirm(answer)
    assert accepted is True
    assert "fix/x" in said[0]
    assert "файлів 1: f0.py" in said[0]


def test_already_confirmed_launcher_is_not_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch, "fix/x", 1)
    assert _confirm(None, {guard.ACCEPT_ENV: "1"}) == (True, [])


@pytest.mark.parametrize(("answer", "accepted"), [("т", True), ("", False), (None, False)])
def test_git_unavailable_is_asked_too(
    monkeypatch: pytest.MonkeyPatch, answer: str | None, accepted: bool
) -> None:
    monkeypatch.setattr(guard, "read_checkout", lambda _root: None)
    result, said = _confirm(answer)
    assert result is accepted
    assert said[0] == guard.UNKNOWN


def test_closed_stdin_aborts_without_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch, "fix/x", 0)

    def ask(_prompt: str) -> str:
        raise RuntimeError("input(): lost sys.stdin")

    assert guard.confirm_console(ROOT, {}, ask=ask, say=lambda _text: None) is False


def test_warning_names_the_first_changed_files() -> None:
    state = guard.Checkout("main", tuple(f"f{i}.py" for i in range(7)))
    text = guard.warning_text(state)
    assert "файлів 7: f0.py, f1.py, f2.py, f3.py, f4.py і ще 2." in text


def test_read_checkout_reports_branch_and_changed_files(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    git("add", "a.txt")
    git("commit", "-m", "init")
    assert guard.read_checkout(tmp_path) == guard.Checkout("main")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    git("switch", "-c", "topic")
    assert guard.read_checkout(tmp_path) == guard.Checkout("topic", ("b.txt",))


def test_read_checkout_outside_a_repository_is_unknown(tmp_path: Path) -> None:
    assert guard.read_checkout(tmp_path / "missing") is None

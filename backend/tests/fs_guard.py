"""Test-run guard: no test may write the developer's real `.env` (or `.env.*` besides
`.env.example`), `backups/` or `data/` in the repo root (owner bug 2026-11-20).

Installed once per pytest process by conftest via `sys.addaudithook`. A blocked write raises
`ProtectedPathWriteError` (the operation is aborted) and is recorded, so an autouse fixture
fails the test even if the code under test swallows the exception. Paths are compared with
`os.path.abspath` + `normcase` only (no filesystem calls inside the hook).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_NAME = ".env"
ALLOWED_ENV_FILES = frozenset({".env.example"})
PROTECTED_DIRS = ("backups", "data")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# Audit events whose path arguments are all writes (rename/replace: both ends).
PATH_EVENTS: dict[str, tuple[int, ...]] = {
    "os.rename": (0, 1),
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.truncate": (0,),
    "os.link": (1,),
    "os.symlink": (1,),
    "shutil.copyfile": (1,),
    "shutil.rmtree": (0,),
}


class ProtectedPathWriteError(RuntimeError):
    """A test tried to write a protected repo path."""


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _as_str(value: Any) -> str | None:
    if isinstance(value, int | type(None)):
        return None  # file descriptor or no path
    try:
        raw = os.fsdecode(os.fspath(value))
    except TypeError:
        return None
    return raw or None


@dataclass
class FsGuard:
    repo_root: Path = REPO_ROOT
    violations: list[str] = field(default_factory=list)
    paused: bool = False  # only the guard's own cleanup in test_fs_guard.py sets this

    def __post_init__(self) -> None:
        self._root = _norm(str(self.repo_root))
        self._dirs = tuple(_norm(str(self.repo_root / name)) for name in PROTECTED_DIRS)
        self._allowed = {os.path.normcase(name) for name in ALLOWED_ENV_FILES}

    def is_protected(self, path: str) -> bool:
        norm = _norm(path)
        parent, name = os.path.split(norm)
        if parent == self._root:
            env = os.path.normcase(ENV_NAME)
            if name == env or (name.startswith(env + ".") and name not in self._allowed):
                return True
        return any(norm == d or norm.startswith(d + os.sep) for d in self._dirs)

    def written_paths(self, event: str, args: Sequence[Any]) -> list[str]:
        """The paths an audit event writes (empty for reads and unrelated events)."""
        if event == "open":
            path, mode, flags = [*args, None, None, None][:3]  # open: (path, mode, flags)
            writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & WRITE_FLAGS)
            )
            target = _as_str(path)
            return [target] if writes and target else []
        positions = PATH_EVENTS.get(event, ())
        return [p for i in positions if i < len(args) and (p := _as_str(args[i]))]

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if self.paused or (event != "open" and event not in PATH_EVENTS):
            return
        for path in self.written_paths(event, args):
            if self.is_protected(path):
                message = f"{event} on protected repo path {path!r}"
                self.violations.append(message)
                raise ProtectedPathWriteError(
                    f"{message}: tests must use tmp_path (see tests/fs_guard.py)"
                )

    def take(self) -> list[str]:
        """Return and clear the recorded violations."""
        taken, self.violations = self.violations, []
        return taken


GUARD = FsGuard()

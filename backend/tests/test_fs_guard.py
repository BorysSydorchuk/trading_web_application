"""The test-run guard (tests/fs_guard.py): writes to the real .env, backups/ and data/ are
blocked and recorded; reads and tmp paths pass. Live probes use names that do not exist
(`.env.guard-probe`, `backups/guard-probe.tmp`), never the real .env."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.fs_guard import GUARD, REPO_ROOT, FsGuard, ProtectedPathWriteError


@pytest.fixture
def guard(tmp_path: Path) -> FsGuard:
    return FsGuard(repo_root=tmp_path)


@pytest.mark.parametrize(
    "name",
    [".env", ".env.bak-20261120T161904Z", ".env.native-pg.tmp", "backups/x.dump", "data/a/b.json"],
)
def test_protected_paths(guard: FsGuard, tmp_path: Path, name: str) -> None:
    assert guard.is_protected(str(tmp_path / name))


@pytest.mark.parametrize(
    "name", [".env.example", "backend/.env", "logs/api.log", "backups.txt", "database/x"]
)
def test_unprotected_paths(guard: FsGuard, tmp_path: Path, name: str) -> None:
    assert not guard.is_protected(str(tmp_path / name))


def test_write_events_are_detected_reads_are_not(guard: FsGuard, tmp_path: Path) -> None:
    env = str(tmp_path / ".env")
    assert guard.written_paths("open", (env, "r", os.O_RDONLY)) == []
    assert guard.written_paths("open", (env, "rb", os.O_RDONLY)) == []
    assert guard.written_paths("open", (env, "a", 0)) == [env]
    assert guard.written_paths("open", (env, "r+", 0)) == [env]
    assert guard.written_paths("open", (env, None, os.O_WRONLY | os.O_CREAT)) == [env]
    assert guard.written_paths("open", (3, "w", 0)) == []  # a file descriptor, no path
    assert guard.written_paths("os.rename", ("a.tmp", env, None, None)) == ["a.tmp", env]
    assert guard.written_paths("shutil.copyfile", ("src", env)) == [env]
    assert guard.written_paths("socket.connect", (None, ("127.0.0.1", 1))) == []


def test_hook_raises_and_records(guard: FsGuard, tmp_path: Path) -> None:
    guard.hook("open", (str(tmp_path / "ok.txt"), "w", 0))
    with pytest.raises(ProtectedPathWriteError, match="tmp_path"):
        guard.hook("os.rename", (str(tmp_path / "x.tmp"), str(tmp_path / ".env"), None, None))
    assert len(guard.take()) == 1
    assert guard.take() == []


def test_installed_guard_blocks_real_repo_writes() -> None:
    """The conftest hook is live: real writes into the repo's protected paths are aborted."""
    probe = REPO_ROOT / ".env.guard-probe"
    backup_probe = REPO_ROOT / "backups" / "guard-probe.tmp"
    try:
        with pytest.raises(ProtectedPathWriteError):
            probe.write_text("x", encoding="utf-8")
        with pytest.raises(ProtectedPathWriteError):
            shutil.copyfile(__file__, backup_probe)
        assert not probe.exists()
        assert not backup_probe.exists()
    finally:
        blocked = GUARD.take()  # expected here; do not fail this test at teardown
        GUARD.paused = True  # only if the guard failed: never leave a junk probe file
        try:
            probe.unlink(missing_ok=True)
            backup_probe.unlink(missing_ok=True)
        finally:
            GUARD.paused = False
    assert len(blocked) == 2


def test_installed_guard_allows_tmp_writes(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")
    os.replace(target, tmp_path / ".env2")
    assert (tmp_path / ".env2").read_text(encoding="utf-8") == "A=1\n"

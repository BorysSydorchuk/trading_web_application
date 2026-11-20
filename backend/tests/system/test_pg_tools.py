"""app.system.pg_tools: PATH first, then a native EDB install under a fake PROGRAMFILES."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.system import pg_tools
from app.system.pg_tools import native_bin_dirs, pg_tool


def _install(root: Path, version: str, *tools: str) -> Path:
    bin_dir = root / "PostgreSQL" / version / "bin"
    bin_dir.mkdir(parents=True)
    for tool in tools:
        (bin_dir / f"{tool}.exe").write_bytes(b"")
    return bin_dir


def _no_path(_name: str) -> str | None:
    return None


def test_path_wins_over_native(tmp_path: Path) -> None:
    _install(tmp_path, "16", "pg_dump")
    found = pg_tool("pg_dump", which=lambda n: f"/usr/bin/{n}", program_files=str(tmp_path))
    assert found == "/usr/bin/pg_dump"


def test_native_16_preferred_over_newer(tmp_path: Path) -> None:
    _install(tmp_path, "17", "pg_dump")
    bin16 = _install(tmp_path, "16", "pg_dump")
    assert pg_tool("pg_dump", which=_no_path, program_files=str(tmp_path)) == str(
        bin16 / "pg_dump.exe"
    )


def test_newest_major_without_16(tmp_path: Path) -> None:
    _install(tmp_path, "15", "pg_restore")
    bin17 = _install(tmp_path, "17", "pg_restore")
    _install(tmp_path, "pgAdmin 4", "pg_restore")  # not a version dir: ignored
    assert pg_tool("pg_restore", which=_no_path, program_files=str(tmp_path)) == str(
        bin17 / "pg_restore.exe"
    )


def test_falls_through_to_install_that_has_the_tool(tmp_path: Path) -> None:
    _install(tmp_path, "16")  # server-only bin without pg_dump
    bin15 = _install(tmp_path, "15", "pg_dump")
    assert pg_tool("pg_dump", which=_no_path, program_files=str(tmp_path)) == str(
        bin15 / "pg_dump.exe"
    )


@pytest.mark.parametrize("program_files", [None, ""])
def test_no_program_files(program_files: str | None) -> None:
    assert native_bin_dirs(program_files) == []


def test_missing_postgresql_dir(tmp_path: Path) -> None:
    assert pg_tool("pg_dump", which=_no_path, program_files=str(tmp_path)) is None


def test_default_program_files_and_live_which(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin16 = _install(tmp_path, "16", "psql")
    monkeypatch.setattr(pg_tools, "default_program_files", lambda: str(tmp_path))
    monkeypatch.setattr("shutil.which", _no_path)
    assert pg_tool("psql") == str(bin16 / "psql.exe")
    monkeypatch.setattr("shutil.which", lambda n: n)
    assert pg_tool("psql") == "psql"

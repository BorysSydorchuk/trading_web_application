"""Find PostgreSQL client tools (pg_dump, pg_restore, psql) without PATH changes.

PATH first (`shutil.which`), then a native EDB install under
`%PROGRAMFILES%\\PostgreSQL\\<major>\\bin` (decision 2026-11-20: native PostgreSQL 16
service next to the Docker fallback). Major 16 is preferred (same major as the server and
the Docker image); otherwise the newest installed major. Stdlib only, no subprocesses.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

PREFERRED_MAJOR = 16
PG_DIR_NAME = "PostgreSQL"


def default_program_files() -> str | None:
    """`%PROGRAMFILES%`; tests replace this to keep a real install out of their way."""
    return os.environ.get("PROGRAMFILES")


def _major(name: str) -> int | None:
    head = name.split(".", 1)[0]
    return int(head) if head.isdecimal() else None


def native_bin_dirs(program_files: str | None) -> list[Path]:
    """Existing `<program_files>/PostgreSQL/<major>/bin` dirs, preferred first."""
    if not program_files:
        return []
    root = Path(program_files) / PG_DIR_NAME
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    found: list[tuple[int, Path]] = []
    for child in children:
        major = _major(child.name)
        if major is not None and (child / "bin").is_dir():
            found.append((major, child / "bin"))
    found.sort(key=lambda item: (item[0] != PREFERRED_MAJOR, -item[0]))
    return [path for _major_number, path in found]


def native_tool(name: str, program_files: str | None) -> str | None:
    """`<bin>/<name>.exe` in the preferred native install that has it, else None."""
    exe = name if name.lower().endswith(".exe") else f"{name}.exe"
    for directory in native_bin_dirs(program_files):
        candidate = directory / exe
        if candidate.is_file():
            return str(candidate)
    return None


def pg_tool(
    name: str,
    *,
    which: Callable[[str], str | None] | None = None,
    program_files: str | None = None,
) -> str | None:
    """`shutil.which(name)`, else the native EDB install's tool, else None.

    `which`/`program_files` default to the live `shutil.which` / `%PROGRAMFILES%` looked up
    at call time, so monkeypatching `shutil.which` in tests keeps working.
    """
    found = (which or shutil.which)(name)
    if found:
        return found
    root = program_files if program_files is not None else default_program_files()
    return native_tool(name, root)

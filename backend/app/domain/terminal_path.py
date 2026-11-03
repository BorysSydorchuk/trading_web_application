"""Terminal path guard: an MT5 terminal must not run from Program Files (MT5_SETUP.md step 1).

Windows does not let the terminal write there (Edge WebView inside MT5 fails, portable mode
breaks), so the API rejects such a ``terminal_path`` and the worker refuses to start it.

Pure string logic, no file system access, so it behaves the same on any OS and in tests:
the environment is passed in (``env``) and Windows path rules are applied with ``ntpath``.
"""

from __future__ import annotations

import ntpath
import os
import re
from collections.abc import Mapping

TERMINAL_EXE = "terminal64.exe"

# Stable code: API `details.field_codes.terminal_path` and worker `Mt5ErrorCode`.
PROGRAM_FILES_CODE = "terminal_in_program_files"
PROGRAM_FILES_MESSAGE = (
    "the terminal must not be under C:\\Program Files; copy it to a portable folder "
    "such as D:\\MT5\\<account-name>\\ first (docs/MT5_SETUP.md step 1)"
)

# Always forbidden, whatever the env vars say (incl. 8.3 short names of the two roots).
_LITERAL_ROOTS = (
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\PROGRA~1",
    "C:\\PROGRA~2",
)
# Also forbidden: wherever these point on this machine (when set to an absolute folder).
PROGRAM_FILES_ENV_VARS = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramFiles(Arm)")

_ENV_VAR = re.compile(r"%([^%]+)%")
_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\")

# (drive, components), case-folded; drive "" = rooted path on the current drive.
_PathKey = tuple[str, tuple[str, ...]]


def expand_env_vars(path: str, env: Mapping[str, str]) -> str:
    """Expand ``%NAME%`` like cmd.exe: names case-insensitive, unknown left as is, one pass."""
    lookup = {key.casefold(): value for key, value in env.items()}

    def replace(match: re.Match[str]) -> str:
        return lookup.get(match.group(1).casefold(), match.group(0))

    return _ENV_VAR.sub(replace, path)


def _strip_quotes(path: str) -> str:
    """Same as the worker: surrounding whitespace and double quotes."""
    return path.strip().strip('"').strip()


def _path_key(path: str) -> _PathKey | None:
    """Normalised absolute path as (drive, parts); None for relative paths (cannot decide)."""
    text = path.replace("/", "\\")
    if text.startswith(_DEVICE_PREFIXES):
        text = text[len(_DEVICE_PREFIXES[0]) :]
    drive, tail = ntpath.splitdrive(ntpath.normpath(text))
    if not tail.startswith("\\"):
        return None
    # Windows ignores trailing dots and spaces of a component ("Program Files." = "Program Files").
    parts = tuple(p.rstrip(" .").casefold() for p in tail.split("\\") if p)
    return drive.casefold(), parts


def _forbidden_roots(env: Mapping[str, str]) -> list[_PathKey]:
    lookup = {key.casefold(): value for key, value in env.items()}
    candidates = list(_LITERAL_ROOTS)
    candidates += [lookup.get(name.casefold(), "") for name in PROGRAM_FILES_ENV_VARS]
    roots: list[_PathKey] = []
    for candidate in candidates:
        key = _path_key(_strip_quotes(candidate))
        # Ignore broken values (blank, relative, a bare drive): they must not forbid everything.
        if key is not None and key[0] and key[1]:
            roots.append(key)
    return roots


def _is_under(path: _PathKey, root: _PathKey) -> bool:
    drive, parts = path
    root_drive, root_parts = root
    # A rooted path without a drive is on the current drive, which may be the root's drive.
    same_drive = drive in ("", root_drive)
    return same_drive and parts[: len(root_parts)] == root_parts


def is_in_program_files(path: str, env: Mapping[str, str] | None = None) -> bool:
    """True if ``path`` (file or folder) is inside a Program Files folder.

    Quotes are stripped, ``%VAR%`` expanded from ``env`` (default: the process environment),
    slashes, repeated separators and ``.``/``..`` normalised, case ignored.
    """
    environment = os.environ if env is None else env
    key = _path_key(expand_env_vars(_strip_quotes(path), environment))
    if key is None:
        return False
    return any(_is_under(key, root) for root in _forbidden_roots(environment))

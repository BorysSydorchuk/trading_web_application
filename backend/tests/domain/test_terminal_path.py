"""Terminal path guard (DECISIONS 2026-11-03, MT5_SETUP.md step 1)."""

from __future__ import annotations

import pytest

from app.domain.terminal_path import expand_env_vars, is_in_program_files

# A machine where the env vars point to the default locations.
DEFAULT_ENV = {
    "ProgramFiles": "C:\\Program Files",
    "ProgramFiles(x86)": "C:\\Program Files (x86)",
    "ProgramW6432": "C:\\Program Files",
    "MT5_HOME": "D:\\MT5",
    "PF_ALIAS": "C:\\Program Files\\FundedNext MT5 Terminal",
}

# Env vars pointing somewhere unusual (relocated Program Files on D:).
MOVED_ENV = {
    "PROGRAMFILES": "D:\\Apps",
    "programfiles(x86)": "D:/Apps (x86)/",
    "ProgramW6432": '"E:\\Win64 Apps"',
}


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Program Files\\FundedNext MT5 Terminal\\terminal64.exe",
        "C:\\Program Files (x86)\\MT5\\terminal64.exe",
        "c:\\program files\\mt5\\terminal64.exe",
        "C:\\PROGRAM FILES (X86)\\MT5\\TERMINAL64.EXE",
        "C:/Program Files/MT5/terminal64.exe",
        "C:\\Program Files/MT5\\terminal64.exe",
        "C:\\\\Program Files\\\\MT5//terminal64.exe",
        '"C:\\Program Files\\MT5\\terminal64.exe"',
        '  "C:\\Program Files\\MT5\\terminal64.exe"  ',
        "C:\\Program Files",
        "C:\\Program Files\\",
        "C:\\Program Files (x86)",
        "C:\\MT5\\..\\Program Files\\x\\terminal64.exe",
        "C:\\Program Files\\MT5\\.\\terminal64.exe",
        "C:\\..\\Program Files\\MT5\\terminal64.exe",
    ],
)
def test_literal_roots_forbidden(path: str) -> None:
    assert is_in_program_files(path, env={})
    assert is_in_program_files(path, env=DEFAULT_ENV)
    assert is_in_program_files(path, env=MOVED_ENV)


@pytest.mark.parametrize(
    "path",
    [
        "C:\\PROGRA~1\\MT5\\terminal64.exe",
        "C:\\progra~2\\MT5\\terminal64.exe",
        "C:/Progra~1/terminal64.exe",
    ],
)
def test_short_names_forbidden(path: str) -> None:
    assert is_in_program_files(path, env={})


@pytest.mark.parametrize(
    "path",
    [
        "\\\\?\\C:\\Program Files\\MT5\\terminal64.exe",
        "\\\\.\\C:\\Program Files\\MT5\\terminal64.exe",
        "//?/C:/Program Files/MT5/terminal64.exe",
    ],
)
def test_device_prefixes_forbidden(path: str) -> None:
    assert is_in_program_files(path, env={})


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Program Files.\\MT5\\terminal64.exe",
        "C:\\Program Files \\MT5\\terminal64.exe",
        "C:\\Program Files (x86). \\MT5\\terminal64.exe",
    ],
)
def test_trailing_dots_and_spaces_forbidden(path: str) -> None:
    """Windows drops trailing dots/spaces of a path component, so these are Program Files."""
    assert is_in_program_files(path, env={})


@pytest.mark.parametrize(
    "path",
    [
        "\\Program Files\\MT5\\terminal64.exe",
        "/Program Files (x86)/MT5/terminal64.exe",
    ],
)
def test_rooted_path_without_drive_forbidden(path: str) -> None:
    """A rooted path without a drive is on the current drive, which may be C:."""
    assert is_in_program_files(path, env={})


@pytest.mark.parametrize(
    "path",
    [
        "%ProgramFiles%\\MT5\\terminal64.exe",
        "%PROGRAMFILES%\\MT5\\terminal64.exe",
        "%programfiles(x86)%\\MT5\\terminal64.exe",
        "%ProgramW6432%/MT5/terminal64.exe",
        "%PF_ALIAS%\\terminal64.exe",
        '"%ProgramFiles%\\MT5\\terminal64.exe"',
    ],
)
def test_env_vars_expanding_to_program_files_forbidden(path: str) -> None:
    assert is_in_program_files(path, env=DEFAULT_ENV)


@pytest.mark.parametrize(
    "path",
    [
        "D:\\Apps\\MT5\\terminal64.exe",
        "d:/apps/MT5/terminal64.exe",
        "D:\\Apps (x86)\\MT5\\terminal64.exe",
        "E:\\Win64 Apps\\MT5\\terminal64.exe",
        "%ProgramFiles%\\MT5\\terminal64.exe",
        "%ProgramFiles(x86)%\\MT5\\terminal64.exe",
        # The literal well-known roots stay forbidden even when the env vars differ.
        "C:\\Program Files\\MT5\\terminal64.exe",
        "C:\\Program Files (x86)\\MT5\\terminal64.exe",
    ],
)
def test_env_var_targets_forbidden(path: str) -> None:
    assert is_in_program_files(path, env=MOVED_ENV)


@pytest.mark.parametrize(
    "path",
    [
        "D:\\MT5\\fn-p1\\terminal64.exe",
        "C:\\MT5\\terminal64.exe",
        "C:\\Program Files Backup\\MT5\\terminal64.exe",
        "C:\\Program Files (x86) Old\\MT5\\terminal64.exe",
        "C:\\ProgramFiles\\MT5\\terminal64.exe",
        "D:\\Program Files\\MT5\\terminal64.exe",
        "D:\\Program Files (x86)\\MT5\\terminal64.exe",
        "C:\\MT5\\Program Files\\terminal64.exe",
        "C:\\Users\\Borys\\Program Files\\MT5\\terminal64.exe",
        "C:\\PROGRA~3\\MT5\\terminal64.exe",
        "C:\\PROGRA~10\\MT5\\terminal64.exe",
        "C:\\Program Files\\..\\MT5\\terminal64.exe",
        "%MT5_HOME%\\fn-p1\\terminal64.exe",
        "%UNKNOWN%\\terminal64.exe",
        "Program Files\\MT5\\terminal64.exe",
        "\\\\server\\share\\Program Files\\MT5\\terminal64.exe",
        "",
        "   ",
    ],
)
def test_lookalikes_allowed(path: str) -> None:
    assert not is_in_program_files(path, env=DEFAULT_ENV)


def test_d_program_files_forbidden_only_as_env_target() -> None:
    path = "D:\\Program Files\\MT5\\terminal64.exe"
    assert not is_in_program_files(path, env=DEFAULT_ENV)
    assert is_in_program_files(path, env={"ProgramFiles": "D:\\Program Files"})


@pytest.mark.parametrize("value", ["", "   ", "C:\\", "C:", "relative\\dir", "\\"])
def test_degenerate_env_values_ignored(value: str) -> None:
    """A broken env var must not forbid a whole drive (or everything)."""
    env = {"ProgramFiles": value}
    assert not is_in_program_files("C:\\MT5\\terminal64.exe", env=env)
    assert not is_in_program_files("D:\\MT5\\terminal64.exe", env=env)


def test_default_env_is_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ProgramFiles", "Q:\\Relocated")
    assert is_in_program_files("Q:\\Relocated\\MT5\\terminal64.exe")
    assert is_in_program_files("C:\\Program Files\\MT5\\terminal64.exe")
    assert not is_in_program_files("D:\\MT5\\terminal64.exe")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("%ProgramFiles%\\x", "C:\\Program Files\\x"),
        ("%programfiles%\\x", "C:\\Program Files\\x"),
        ("%PROGRAMFILES(X86)%\\x", "C:\\Program Files (x86)\\x"),
        ("%MT5_HOME%\\%UNKNOWN%\\x", "D:\\MT5\\%UNKNOWN%\\x"),
        ("100%\\x", "100%\\x"),
        ("%%", "%%"),
        ("no vars", "no vars"),
    ],
)
def test_expand_env_vars(raw: str, expected: str) -> None:
    assert expand_env_vars(raw, DEFAULT_ENV) == expected


def test_expand_env_vars_is_single_pass() -> None:
    """Like cmd.exe: a value containing %X% is not expanded again (no recursion)."""
    env = {"A": "%B%", "B": "C:\\Program Files"}
    assert expand_env_vars("%A%\\x", env) == "%B%\\x"

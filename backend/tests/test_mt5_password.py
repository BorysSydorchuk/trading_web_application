"""`mt5_password_for`: env var beats .env, empty means unset, the value stays secret."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import mt5_password_for, mt5_password_key

LOGIN = 90000042
KEY = f"MT5_PASSWORD_{LOGIN}"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY, raising=False)


def _env_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    return path


def test_key_name() -> None:
    assert mt5_password_key(LOGIN) == KEY


def test_missing_file_and_env(tmp_path: Path) -> None:
    assert mt5_password_for(LOGIN, env_file=tmp_path / "absent.env") is None


def test_read_from_env_file(tmp_path: Path) -> None:
    path = _env_file(tmp_path, f"OTHER=1\n{KEY}=from-file\n")
    secret = mt5_password_for(LOGIN, env_file=path)
    assert secret is not None
    assert secret.get_secret_value() == "from-file"
    assert "from-file" not in repr(secret)
    assert "from-file" not in str(secret)


def test_env_file_key_case_insensitive(tmp_path: Path) -> None:
    path = _env_file(tmp_path, f"{KEY.lower()}=from-file\n")
    secret = mt5_password_for(LOGIN, env_file=path)
    assert secret is not None


def test_environment_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _env_file(tmp_path, f"{KEY}=from-file\n")
    monkeypatch.setenv(KEY, "from-env")
    secret = mt5_password_for(LOGIN, env_file=path)
    assert secret is not None
    assert secret.get_secret_value() == "from-env"


@pytest.mark.parametrize("content", [f"{KEY}=\n", f"{KEY}=   \n", f"# {KEY}=commented\n"])
def test_empty_or_commented_is_unset(tmp_path: Path, content: str) -> None:
    assert mt5_password_for(LOGIN, env_file=_env_file(tmp_path, content)) is None


def test_other_login_not_matched(tmp_path: Path) -> None:
    path = _env_file(tmp_path, f"MT5_PASSWORD_{LOGIN + 1}=x\nMT5_PASSWORD_{LOGIN}0=y\n")
    assert mt5_password_for(LOGIN, env_file=path) is None

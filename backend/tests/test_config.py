from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ENV_FILE, REPO_ROOT, Settings
from app.logging_setup import setup_logging

_SETTINGS_ENV_VARS = (
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "LOG_DIR",
    "LOG_LEVEL",
    "API_PORT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL_EXTRACTION",
    "ANTHROPIC_MODEL_SUMMARY",
    "ANTHROPIC_MODEL_FALLBACK",
    "ANTHROPIC_EFFORT",
    "POSTGRES_PASSWORD",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _write_env(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_env_file_is_repo_root() -> None:
    assert (REPO_ROOT / "backend" / "pyproject.toml").is_file()
    assert ENV_FILE == REPO_ROOT / ".env"


def test_loads_values_from_env_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(
        tmp_path / ".env",
        "DATABASE_URL=postgresql+psycopg://u:topsecret@127.0.0.1:5432/db\n"
        "LOG_LEVEL=DEBUG\n"
        "API_PORT=9001\n"
        "ANTHROPIC_API_KEY=sk-ant-hidden\n"
        "MT5_PASSWORD_FN_P1=investor\n",  # unknown keys are ignored
    )
    settings = Settings(_env_file=env)

    assert settings.database_url.endswith("/db")
    assert settings.log_level == "DEBUG"
    assert settings.api_port == 9001
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-hidden"


def test_environment_overrides_env_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(tmp_path / ".env", "DATABASE_URL=postgresql+psycopg://a@h/x\nAPI_PORT=9001\n")
    clean_env.setenv("API_PORT", "9002")
    settings = Settings(_env_file=env)
    assert settings.api_port == 9002


def test_secrets_not_in_repr(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(
        tmp_path / ".env",
        "DATABASE_URL=postgresql+psycopg://u:topsecret@127.0.0.1:5432/db\n"
        "POSTGRES_PASSWORD=topsecret\n"
        "ANTHROPIC_API_KEY=sk-ant-hidden\n",
    )
    settings = Settings(_env_file=env)
    for rendered in (repr(settings), str(settings)):
        assert "topsecret" not in rendered
        assert "sk-ant-hidden" not in rendered


def test_ai_settings_defaults_and_empty_key(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(tmp_path / ".env", "DATABASE_URL=postgresql+psycopg://a@h/x\n")
    settings = Settings(_env_file=env)
    assert settings.anthropic_model_extraction == "claude-sonnet-5-5"
    assert settings.anthropic_model_summary == "claude-opus-5-5"
    assert settings.anthropic_model_fallback == "claude-opus-5-5"
    assert settings.anthropic_effort == "low"
    assert settings.anthropic_api_key.get_secret_value() == ""
    assert settings.ai_configured is False


def test_ai_settings_from_env_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(
        tmp_path / ".env",
        "DATABASE_URL=postgresql+psycopg://a@h/x\n"
        "ANTHROPIC_API_KEY=sk-ant-hidden\n"
        "ANTHROPIC_MODEL_EXTRACTION=claude-opus-5-5\n"
        "ANTHROPIC_MODEL_FALLBACK=claude-sonnet-5-5\n"
        "ANTHROPIC_EFFORT=low\n",
    )
    settings = Settings(_env_file=env)
    assert settings.anthropic_model_extraction == "claude-opus-5-5"
    assert settings.anthropic_model_fallback == "claude-sonnet-5-5"
    assert settings.anthropic_effort == "low"
    assert settings.ai_configured is True


def test_blank_key_is_not_configured(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(tmp_path / ".env", "DATABASE_URL=postgresql+psycopg://a@h/x\n")
    clean_env.setenv("ANTHROPIC_API_KEY", "   ")
    assert Settings(_env_file=env).ai_configured is False


@pytest.mark.parametrize("effort", ["max", "xhigh", "MEDIUMish", ""])
def test_invalid_effort_rejected(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, effort: str
) -> None:
    env = _write_env(tmp_path / ".env", "DATABASE_URL=postgresql+psycopg://a@h/x\n")
    clean_env.setenv("ANTHROPIC_EFFORT", effort)
    with pytest.raises(ValidationError, match="anthropic_effort"):
        Settings(_env_file=env)


def test_missing_database_url_fails_clearly(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(tmp_path / ".env", "LOG_LEVEL=INFO\n")
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=env)


def test_relative_log_dir_resolves_against_repo_root(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = _write_env(tmp_path / ".env", "DATABASE_URL=postgresql+psycopg://a@h/x\nLOG_DIR=logs\n")
    settings = Settings(_env_file=env)
    assert settings.log_dir_path == REPO_ROOT / "logs"


def test_setup_logging_writes_file_in_utc(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_dir = tmp_path / "nested" / "logs"
    env = _write_env(
        tmp_path / ".env", f"DATABASE_URL=postgresql+psycopg://a@h/x\nLOG_DIR={log_dir}\n"
    )
    settings = Settings(_env_file=env)

    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        log_path = setup_logging("worker.log", settings)
        setup_logging("worker.log", settings)  # idempotent: no duplicate handlers
        logging.getLogger("tests.config").info("hello from test")
        for handler in root.handlers:
            handler.flush()
        content = log_path.read_text(encoding="utf-8")
        ours = [h for h in root.handlers if getattr(h, "_trading_journal_handler", False)]
    finally:
        for handler in list(root.handlers):
            if handler not in saved[0]:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(saved[1])

    assert log_path == log_dir / "worker.log"
    assert content.count("hello from test") == 1
    assert "Z INFO" in content
    assert len(ours) == 2


@pytest.mark.parametrize("level", ["DEBUG", "WARNING"])
def test_http_and_sdk_loggers_never_log_debug(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, level: str
) -> None:
    env = _write_env(
        tmp_path / ".env",
        "DATABASE_URL=postgresql+psycopg://a@h/x\n"
        f"LOG_DIR={tmp_path / 'logs'}\n"
        f"LOG_LEVEL={level}\n",
    )
    settings = Settings(_env_file=env)
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        setup_logging("x.log", settings)
        levels = {
            name: logging.getLogger(name).getEffectiveLevel()
            for name in ("anthropic", "httpx", "httpx2", "httpcore", "httpcore2")
        }
    finally:
        for handler in list(root.handlers):
            if handler not in saved[0]:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(saved[1])
    expected = max(logging.INFO, logging.getLevelName(level))
    assert set(levels.values()) == {expected}

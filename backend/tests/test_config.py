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
    "DATA_DIR",
    "LOG_LEVEL",
    "API_PORT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL_EXTRACTION",
    "ANTHROPIC_MODEL_SUMMARY",
    "ANTHROPIC_MODEL_FALLBACK",
    "ANTHROPIC_EFFORT",
    "POSTGRES_PASSWORD",
    "WHISPER_MODEL",
    "WHISPER_BEAM_SIZE",
    "WHISPER_CPU_THREADS",
    "WHISPER_VAD_FILTER",
    "WHISPER_CONDITION_ON_PREVIOUS_TEXT",
    "WHISPER_TEMPERATURES",
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


def test_data_dir_defaults_to_repo_data_and_is_absolute(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = _write_env(tmp_path / ".env", "DATABASE_URL=postgresql+psycopg://a@h/x\n")
    assert Settings(_env_file=env).data_dir == (REPO_ROOT / "data").resolve()

    clean_env.setenv("DATA_DIR", str(tmp_path / "d"))
    assert Settings(_env_file=env).data_dir == (tmp_path / "d").resolve()


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


_DB_LINE = "DATABASE_URL=postgresql+psycopg://a@h/x\n"


def test_whisper_defaults(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE))
    assert settings.whisper_model == "small"
    assert settings.whisper_beam_size == 1
    assert settings.whisper_cpu_threads == "auto"
    assert settings.whisper_vad_filter is True
    assert settings.whisper_condition_on_previous_text is True
    assert settings.whisper_temperatures == (0.0, 0.4)


def test_whisper_settings_from_env_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _write_env(
        tmp_path / ".env",
        _DB_LINE + "WHISPER_BEAM_SIZE=5\n"
        "WHISPER_CPU_THREADS=0\n"
        "WHISPER_VAD_FILTER=false\n"
        "WHISPER_CONDITION_ON_PREVIOUS_TEXT=false\n"
        "WHISPER_TEMPERATURES= 0.0, 0.2 ,0.4,0.6,0.8,1.0\n",
    )
    settings = Settings(_env_file=env)
    assert settings.whisper_beam_size == 5
    assert settings.whisper_cpu_threads == 0
    assert settings.whisper_vad_filter is False
    assert settings.whisper_condition_on_previous_text is False
    assert settings.whisper_temperatures == (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", (0.0,)), ("0.0,0.4", (0.0, 0.4)), ("0.2", (0.2,)), ("1", (1.0,))],
)
def test_whisper_temperatures_parsed(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, raw: str, expected: tuple[float, ...]
) -> None:
    clean_env.setenv("WHISPER_TEMPERATURES", raw)
    assert Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE)).whisper_temperatures == (
        expected
    )


@pytest.mark.parametrize(
    "raw", ["", " ", "0,", "0,,0.4", "abc", "0.4,0.2", "0,0", "-0.1", "1.5", "nan", "[0, 0.4]"]
)
def test_invalid_whisper_temperatures_rejected(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, raw: str
) -> None:
    clean_env.setenv("WHISPER_TEMPERATURES", raw)
    with pytest.raises(ValidationError, match="whisper_temperatures"):
        Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE))


@pytest.mark.parametrize(
    ("raw", "expected"), [("auto", "auto"), (" AUTO ", "auto"), ("0", 0), ("8", 8), ("256", 256)]
)
def test_whisper_cpu_threads_parsed(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, raw: str, expected: int | str
) -> None:
    clean_env.setenv("WHISPER_CPU_THREADS", raw)
    assert Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE)).whisper_cpu_threads == (
        expected
    )


@pytest.mark.parametrize("raw", ["-1", "257", "four", "1.5"])
def test_invalid_whisper_cpu_threads_rejected(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, raw: str
) -> None:
    clean_env.setenv("WHISPER_CPU_THREADS", raw)
    with pytest.raises(ValidationError, match="whisper_cpu_threads"):
        Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE))


@pytest.mark.parametrize("name", ["WHISPER_VAD_FILTER", "WHISPER_CONDITION_ON_PREVIOUS_TEXT"])
@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("0", False), ("off", False)])
def test_whisper_bools_parsed(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, name: str, raw: str, expected: bool
) -> None:
    clean_env.setenv(name, raw)
    settings = Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE))
    assert getattr(settings, name.lower()) is expected


def test_invalid_whisper_bool_rejected(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("WHISPER_VAD_FILTER", "maybe")
    with pytest.raises(ValidationError, match="whisper_vad_filter"):
        Settings(_env_file=_write_env(tmp_path / ".env", _DB_LINE))

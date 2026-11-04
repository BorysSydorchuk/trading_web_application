"""Application settings loaded from the repo-root `.env` file and the environment.

Environment variables take precedence over `.env`. Secret values are typed as
`SecretStr` or hidden from `repr` so they never end up in logs by accident.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[0]=app, [1]=backend, [2]=repo root
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ENV_FILE: Path = REPO_ROOT / ".env"

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
AnthropicEffort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        # .env also holds keys we do not model here (MT5_PASSWORD_<login>).
        extra="ignore",
    )

    # Postgres (POSTGRES_* are used by docker-compose; the app uses the URLs)
    postgres_user: str = "journal"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "trading_journal"
    postgres_port: int = 5432
    # URLs contain the DB password: keep them out of repr/str.
    database_url: str = Field(repr=False)
    test_database_url: str | None = Field(default=None, repr=False)

    # App
    app_env: str = "dev"
    log_dir: Path = Path("logs")
    # Runtime data (audio notes, worker state files). Relative = against the repo root.
    data_dir: Path = Path("data")
    log_level: LogLevel = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_port: int = 5173

    # MT5 data source for the worker: "real" (MetaTrader5 terminals) or
    # "fixture:<path to JSON>" (demo/QA without a terminal, see README).
    mt5_source: str = "real"

    # AI (from M2). An empty key is allowed: the app starts, AI endpoints answer
    # `ai_not_configured` and the manual journal form still works.
    anthropic_api_key: SecretStr = SecretStr("")
    # Trade (and later bias) extraction: mid-tier model (PRD 5, budget 5-7 USD/month).
    anthropic_model_extraction: str = Field(default="claude-sonnet-5-5", min_length=1)
    # Optional weekly/monthly AI summary (M6); unused until then.
    anthropic_model_summary: str = Field(default="claude-opus-5-5", min_length=1)
    # One attempt on this model after the primary failed with overload/5xx/timeout/connection.
    anthropic_model_fallback: str = Field(default="claude-opus-5-5", min_length=1)
    # Extraction is a mapping task: `low` is faster and cheaper; QA measures p95 in M2-07.
    anthropic_effort: AnthropicEffort = "low"

    # Voice notes (M3): local faster-whisper in the worker (docs/api.md M3).
    whisper_model: str = Field(default="small", min_length=1)
    whisper_compute_type: str = Field(default="int8", min_length=1)
    # Language code for Whisper; empty = auto-detect per note.
    whisper_language: str = "uk"
    whisper_beam_size: int = Field(default=5, ge=1, le=20)
    # 0 = library default (CTranslate2 picks the thread count).
    whisper_cpu_threads: int = Field(default=0, ge=0, le=256)

    @property
    def ai_configured(self) -> bool:
        """True when ANTHROPIC_API_KEY is set (non-blank)."""
        return self.anthropic_api_key.get_secret_value().strip() != ""

    @property
    def log_dir_path(self) -> Path:
        """LOG_DIR resolved against the repo root (not the CWD) when relative."""
        path = self.log_dir.expanduser()
        return path if path.is_absolute() else REPO_ROOT / path

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        """DATA_DIR resolved against the repo root (not the CWD) when relative."""
        path = value.expanduser()
        return (path if path.is_absolute() else REPO_ROOT / path).resolve()

    @property
    def whisper_language_code(self) -> str | None:
        """WHISPER_LANGUAGE stripped, or None (auto-detect) when empty."""
        code = self.whisper_language.strip()
        return code or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Call `get_settings.cache_clear()` to reload."""
    return Settings()


MT5_PASSWORD_PREFIX = "MT5_PASSWORD_"  # noqa: S105 - key name, not a secret


def mt5_password_key(login: int) -> str:
    """Name of the `.env` key holding the investor password of an MT5 login."""
    return f"{MT5_PASSWORD_PREFIX}{login}"


def mt5_password_for(login: int, *, env_file: Path | None = None) -> SecretStr | None:
    """Investor (read-only) password for `login`, or None when the key is unset or empty.

    Same sources and precedence as `Settings`: the process environment wins over the
    `.env` file. Read on every call (no cache) so editing `.env` takes effect without a
    restart. The value is wrapped in `SecretStr` and must never be logged or returned.
    """
    key = mt5_password_key(login)
    value = os.environ.get(key)
    if value is None:
        path = ENV_FILE if env_file is None else env_file
        if path.is_file():
            file_values = {k.upper(): v for k, v in dotenv_values(path, encoding="utf-8").items()}
            value = file_values.get(key)
    if value is None or value.strip() == "":
        return None
    return SecretStr(value)

"""Application settings loaded from the repo-root `.env` file and the environment.

Environment variables take precedence over `.env`. Secret values are typed as
`SecretStr` or hidden from `repr` so they never end up in logs by accident.
"""

from __future__ import annotations

import itertools
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/config.py -> parents[0]=app, [1]=backend, [2]=repo root
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ENV_FILE: Path = REPO_ROOT / ".env"

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
AnthropicEffort = Literal["low", "medium", "high"]
CpuThreadsSetting = int | Literal["auto"]
MAX_WHISPER_CPU_THREADS = 256


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
    whisper_beam_size: int = Field(default=1, ge=1, le=20)
    # `auto` = physical core count (detected once), 0 = library default, N = N threads.
    whisper_cpu_threads: CpuThreadsSetting = "auto"
    # Silero VAD (bundled with faster-whisper) skips silence.
    whisper_vad_filter: bool = True
    # On (PM 2026-11-05): keeps the glossary's Latin spellings through long notes.
    whisper_condition_on_previous_text: bool = True
    # Temperature fallback, comma-separated, ascending, each 0..1; `0` = no fallback.
    whisper_temperatures: Annotated[tuple[float, ...], NoDecode] = (0.0, 0.4)

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

    @field_validator("whisper_cpu_threads", mode="before")
    @classmethod
    def _cpu_threads(cls, value: object) -> CpuThreadsSetting:
        """`auto` (any case) or an integer 0..MAX_WHISPER_CPU_THREADS."""
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("", "auto"):
                return "auto"
            if not text.isdigit():
                raise ValueError("must be `auto`, 0 (library default) or a thread count")
            value = int(text)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be `auto`, 0 (library default) or a thread count")
        if not 0 <= value <= MAX_WHISPER_CPU_THREADS:
            raise ValueError(f"must be between 0 and {MAX_WHISPER_CPU_THREADS}")
        return value

    @field_validator("whisper_temperatures", mode="before")
    @classmethod
    def _temperatures(cls, value: object) -> tuple[float, ...]:
        """Comma-separated floats (or a sequence): non-empty, each 0..1, ascending."""
        return parse_temperatures(value)

    @property
    def whisper_language_code(self) -> str | None:
        """WHISPER_LANGUAGE stripped, or None (auto-detect) when empty."""
        code = self.whisper_language.strip()
        return code or None


def parse_temperatures(value: object) -> tuple[float, ...]:
    """WHISPER_TEMPERATURES: `0.0,0.4` -> (0.0, 0.4). Raises ValueError when invalid."""
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if any(part == "" for part in parts):
            raise ValueError("comma-separated numbers expected, e.g. `0.0,0.4`")
        try:
            items = tuple(float(part) for part in parts)
        except ValueError:
            raise ValueError("comma-separated numbers expected, e.g. `0.0,0.4`") from None
    elif isinstance(value, list | tuple):
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
            raise ValueError("numbers expected")
        items = tuple(float(v) for v in value)
    else:
        raise ValueError("comma-separated numbers expected, e.g. `0.0,0.4`")
    if not items:
        raise ValueError("at least one temperature is required (`0` = no fallback)")
    if any(not 0.0 <= t <= 1.0 for t in items):  # also rejects nan
        raise ValueError("each temperature must be between 0 and 1")
    if any(b <= a for a, b in itertools.pairwise(items)):
        raise ValueError("temperatures must be strictly ascending")
    return items


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

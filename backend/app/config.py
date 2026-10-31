"""Application settings loaded from the repo-root `.env` file and the environment.

Environment variables take precedence over `.env`. Secret values are typed as
`SecretStr` or hidden from `repr` so they never end up in logs by accident.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[0]=app, [1]=backend, [2]=repo root
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ENV_FILE: Path = REPO_ROOT / ".env"

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        # .env also holds keys we do not model here (e.g. MT5_PASSWORD_<REF>).
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
    log_level: LogLevel = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_port: int = 5173

    # AI (used from M2)
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"

    @property
    def log_dir_path(self) -> Path:
        """LOG_DIR resolved against the repo root (not the CWD) when relative."""
        path = self.log_dir.expanduser()
        return path if path.is_absolute() else REPO_ROOT / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Call `get_settings.cache_clear()` to reload."""
    return Settings()

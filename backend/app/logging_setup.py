"""Logging to console and a rotating file in LOG_DIR.

Used by the API (`api.log`) and later by the worker (`worker.log`). Timestamps are UTC.
Calling `setup_logging` again replaces the handlers it installed before (idempotent).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import override

from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.log_rotation import ProcessRotatingHandler

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

# Third-party loggers that do not propagate to root; give them our handlers too.
_NON_PROPAGATING_LOGGERS = ("uvicorn", "uvicorn.access")

# HTTP/SDK loggers log request bodies (the prompt and the trade description) at DEBUG:
# never below INFO, whatever LOG_LEVEL is.
_QUIET_LOGGERS = ("anthropic", "httpx", "httpx2", "httpcore", "httpcore2")

_HANDLER_MARK = "_trading_journal_handler"


class UTCFormatter(logging.Formatter):
    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        *,
        secrets: tuple[str, ...] = (),
    ) -> None:
        super().__init__(fmt, datefmt=datefmt)
        self.secrets = secrets

    @override
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        for secret in self.secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        rendered = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+@", r"\1[REDACTED]@", rendered)
        rendered = re.sub(r"(?i)(bearer\s+)[^\s,'\"}]+", r"\1[REDACTED]", rendered)
        rendered = re.sub(
            r"(?i)((?:password|passwd|pwd|api[_-]?key|token|secret)\s*['\"]?\s*[:=]\s*['\"]?)[^\s,'\"}]+",
            r"\1[REDACTED]",
            rendered,
        )
        # Bound even an accidental giant exception/body. Keep the beginning and mark loss.
        encoded = rendered.encode("utf-8", errors="replace")
        if len(encoded) > 65536:
            return encoded[:65536].decode("utf-8", errors="ignore") + " [LOG TRUNCATED]"
        return rendered

    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return time.strftime(datefmt or DATE_FORMAT, time.gmtime(record.created))


def _mark(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _HANDLER_MARK, True)
    return handler


def _remove_ours(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            logger.removeHandler(handler)
            handler.close()


def setup_logging(log_file_name: str = "api.log", settings: Settings | None = None) -> Path:
    """Configure root logging; returns the path of the log file."""
    settings = settings or get_settings()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.log", log_file_name):
        raise ValueError("Application log name must be a plain .log filename")
    log_dir = settings.log_dir_path
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_file_name

    values = [
        settings.anthropic_api_key.get_secret_value(),
        settings.postgres_password.get_secret_value(),
    ]
    for url in (settings.database_url, settings.test_database_url):
        if url:
            with suppress(Exception):  # Never log a malformed connection URL during setup.
                values.append(make_url(url).password or "")
    values.extend(v for k, v in os.environ.items() if k.startswith("MT5_PASSWORD_"))
    secrets = tuple(sorted({v for v in values if v.strip()}, key=len, reverse=True))
    formatter = UTCFormatter(LOG_FORMAT, datefmt=DATE_FORMAT, secrets=secrets)
    console = _mark(logging.StreamHandler(sys.stderr))
    console.setFormatter(formatter)
    file_handler = _mark(
        ProcessRotatingHandler(
            log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8", delay=True
        )
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    _remove_ours(root)
    root.setLevel(settings.log_level)
    root.addHandler(console)
    root.addHandler(file_handler)
    quiet_level = max(logging.INFO, root.level)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(quiet_level)

    # uvicorn already logs to the console itself; only add the file.
    for name in _NON_PROPAGATING_LOGGERS:
        logger = logging.getLogger(name)
        _remove_ours(logger)
        if not logger.propagate:
            for handler in logger.handlers:
                handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return log_path

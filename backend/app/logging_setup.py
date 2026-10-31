"""Logging to console and a rotating file in LOG_DIR.

Used by the API (`api.log`) and later by the worker (`worker.log`). Timestamps are UTC.
Calling `setup_logging` again replaces the handlers it installed before (idempotent).
"""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import override

from app.config import Settings, get_settings

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

# Third-party loggers that do not propagate to root; give them our handlers too.
_NON_PROPAGATING_LOGGERS = ("uvicorn", "uvicorn.access")

_HANDLER_MARK = "_trading_journal_handler"


class UTCFormatter(logging.Formatter):
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
    log_dir = settings.log_dir_path
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_file_name

    formatter = UTCFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    console = _mark(logging.StreamHandler(sys.stderr))
    console.setFormatter(formatter)
    file_handler = _mark(
        RotatingFileHandler(
            log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    _remove_ours(root)
    root.setLevel(settings.log_level)
    root.addHandler(console)
    root.addHandler(file_handler)

    # uvicorn already logs to the console itself; only add the file.
    for name in _NON_PROPAGATING_LOGGERS:
        logger = logging.getLogger(name)
        _remove_ours(logger)
        if not logger.propagate:
            logger.addHandler(file_handler)

    return log_path

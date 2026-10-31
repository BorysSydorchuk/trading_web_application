"""GET /api/health: always 200 while the process is up; reports DB reachability."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

DISTRIBUTION_NAME = "trading-journal-backend"
STATEMENT_TIMEOUT_MS = 2000


class DbHealth(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    time_utc: str
    db: DbHealth


def app_version() -> str:
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _short_reason(exc: SQLAlchemyError) -> str:
    """User-safe reason: never includes the connection string, host or credentials."""
    orig = exc.orig if isinstance(exc, DBAPIError) else None
    orig_name = type(orig).__name__ if orig is not None else ""
    if orig_name == "QueryCanceled":
        return "Database query timed out"
    if orig_name == "ConnectionTimeout":
        # On Windows a refused loopback port also surfaces as a connect timeout.
        return "Database is not reachable (connection timed out)"
    if orig_name == "InsufficientPrivilege" or "authentication" in str(orig).lower():
        return "Database authentication failed"
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return "Database connection lost"
    if orig_name in {"OperationalError", "InterfaceError"} or orig is None:
        return "Database is not reachable"
    return f"Database check failed ({orig_name})"


def check_db(db: Session) -> DbHealth:
    started = time.perf_counter()
    try:
        # SET LOCAL limits the timeout to this transaction only.
        db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        db.execute(text("SELECT 1"))
        error: str | None = None
    except SQLAlchemyError as exc:
        orig = exc.orig if isinstance(exc, DBAPIError) else exc
        logger.warning("DB health check failed: %s: %s", type(orig).__name__, orig)
        error = _short_reason(exc)
    finally:
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.debug("Rollback after health check failed", exc_info=True)
    latency_ms = round((time.perf_counter() - started) * 1000)
    return DbHealth(ok=error is None, latency_ms=latency_ms, error=error)


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db_health = check_db(db)
    return HealthResponse(
        status="ok" if db_health.ok else "degraded",
        version=app_version(),
        time_utc=utc_now_iso(),
        db=db_health,
    )

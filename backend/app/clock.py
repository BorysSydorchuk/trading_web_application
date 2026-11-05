"""Current time as a FastAPI dependency, so tests can pin "now" (override `utc_now`)."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)

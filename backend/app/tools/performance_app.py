"""Benchmark-only clock override; production API and lifespan stay intact."""

from datetime import UTC, datetime

from app.clock import utc_now
from app.main import app

app.dependency_overrides[utc_now] = lambda: datetime(2026, 11, 13, 17, tzinfo=UTC)

"""SQLAlchemy engine, session factory and the FastAPI session dependency (sync, psycopg v3)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# Local DB: connecting should take milliseconds. A short timeout keeps the API
# (and /api/health) responsive when Postgres is down instead of hanging.
CONNECT_TIMEOUT_S = 2

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def make_engine(url: str, *, connect_timeout_s: int = CONNECT_TIMEOUT_S) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,  # survive a DB restart without stale-connection errors
        connect_args={"connect_timeout": connect_timeout_s},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    """Process-wide engine built lazily from Settings.database_url."""
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(get_engine())
    return _session_factory


def dispose_engine() -> None:
    """Close pooled connections and forget the engine (app shutdown, tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request. Endpoints commit explicitly."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

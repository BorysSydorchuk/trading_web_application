"""Shared fixtures. Tests run against TEST_DATABASE_URL, never the dev database."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Point the app at the test DB and a throwaway log dir *before* app.main is imported
# anywhere (it builds the app and configures logging at import time).
_base_settings = get_settings()
if not _base_settings.test_database_url:
    pytest.exit("TEST_DATABASE_URL is not set (see .env.example).", returncode=2)
TEST_DATABASE_URL: str = _base_settings.test_database_url
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="tj-test-logs-")
# Tests never call the real Anthropic API: no key unless a test sets one (with a fake client).
os.environ["ANTHROPIC_API_KEY"] = ""
get_settings.cache_clear()

from app import db as app_db  # noqa: E402
from app.main import create_app  # noqa: E402


def alembic_config(url: str | None = None) -> Config:
    """Alembic config on the test DB. No ini file, so alembic.ini's logging setup is skipped."""
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("path_separator", "os")
    cfg.attributes["sqlalchemy.url"] = url or TEST_DATABASE_URL
    return cfg


def reset_schema(engine: Engine) -> None:
    """Drop everything in `public` (tables, alembic_version) so tests start from zero."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Engine on the test DB; aborts the run with a clear message if it is unreachable."""
    engine = app_db.make_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        engine.dispose()
        safe_url = make_url(TEST_DATABASE_URL).render_as_string(hide_password=True)
        orig = getattr(exc, "orig", exc)
        pytest.exit(
            f"Test database is unreachable ({safe_url}): {type(orig).__name__}. "
            "Start Postgres with `make db-up` (or `docker compose up -d db`) and make sure "
            "the `trading_journal_test` database exists.",
            returncode=3,
        )
    # Fresh schema per session, built by the real migrations (not metadata.create_all).
    reset_schema(engine)
    command.upgrade(alembic_config(), "head")
    yield engine
    engine.dispose()
    app_db.dispose_engine()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    session = app_db.make_session_factory(db_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def app(db_engine: Engine) -> Iterator[FastAPI]:
    application = create_app()
    session_factory = app_db.make_session_factory(db_engine)

    def _get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[app_db.get_db] = _get_db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

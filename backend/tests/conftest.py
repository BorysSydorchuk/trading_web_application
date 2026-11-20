"""Shared fixtures. Tests run against TEST_DATABASE_URL, never the dev database."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from tests.fs_guard import GUARD

BACKEND_DIR = Path(__file__).resolve().parent.parent

# No test may write the real .env, backups/ or data/ (owner bug 2026-11-20); see fs_guard.py.
sys.addaudithook(GUARD.hook)

# Point the app at the test DB and throwaway log/data dirs *before* app.main is imported
# anywhere (it builds the app and configures logging at import time).
_base_settings = get_settings()
if not _base_settings.test_database_url:
    pytest.exit("TEST_DATABASE_URL is not set (see .env.example).", returncode=2)
BASE_TEST_DATABASE_URL: str = _base_settings.test_database_url
TEST_SUFFIX = "_test"
_dev_db = make_url(_base_settings.database_url).database
_test_db = make_url(BASE_TEST_DATABASE_URL).database or ""
if not _test_db.endswith(TEST_SUFFIX) or _test_db == _dev_db:
    pytest.exit(
        f"TEST_DATABASE_URL must name a separate *{TEST_SUFFIX} database (never the dev DB).",
        returncode=2,
    )
SAFE_DB_NAME = re.compile(r"[A-Za-z0-9_]+")


def worker_database_url(base_url: str, worker: str | None) -> str:
    """pytest-xdist: one database per worker, `<name>_<worker>_test` (keeps the `_test`
    suffix the migrate tool and guards rely on). No worker: the base URL unchanged."""
    if not worker:
        return base_url
    url = make_url(base_url)
    name = url.database or ""
    stem = name.removesuffix(TEST_SUFFIX)
    return url.set(database=f"{stem}_{worker}{TEST_SUFFIX}").render_as_string(hide_password=False)


# One-off bases (QA/performance runs, e.g. `tj_m705_20261115194506_33f314_test`) carry a UTC
# run stamp; their per-worker copies are dropped at the end of the run and, if a run died,
# by the next run once older than STALE_AFTER. Fixed names (`trading_journal_gw3_test`)
# have no stamp and are reused by every gate.
RUN_STAMP = re.compile(r"_(\d{14})_")
WORKER_DB = re.compile(r"[A-Za-z0-9_]+_gw\d+_test")
STALE_AFTER = timedelta(hours=24)


def run_stamp(name: str) -> datetime | None:
    """UTC time embedded in a one-off database name, or None for a fixed name."""
    match = RUN_STAMP.search(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def stale_worker_databases(names: Iterable[str], now: datetime, own_base: str) -> list[str]:
    """Per-worker copies of one-off bases whose run stamp is older than STALE_AFTER, except
    the copies of ``own_base`` (a re-run on an old stamped base must not drop its own)."""
    own_prefix = own_base.removesuffix(TEST_SUFFIX) + "_gw"
    stale = []
    for name in names:
        stamp = run_stamp(name)
        if (
            WORKER_DB.fullmatch(name)
            and not name.startswith(own_prefix)
            and stamp is not None
            and now - stamp > STALE_AFTER
        ):
            stale.append(name)
    return sorted(stale)


def drop_statements(names: Iterable[str]) -> list[str]:
    """DROP statements for worker copies only; any other name is skipped (the f-string
    below needs a safe name, and a base or fixed DB must never be dropped here)."""
    return [
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
        for name in names
        if WORKER_DB.fullmatch(name)
    ]


def _cleanup_problem(what: str, exc: SQLAlchemyError) -> None:
    """A cleanup failure never fails the run (the 24 h sweep catches leftovers); it is shown."""
    orig = getattr(exc, "orig", exc)
    print(f"[test DB cleanup] {what}: {type(orig).__name__}", file=sys.stderr)


def _drop_databases(base_url: str, names: Iterable[str]) -> None:
    engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in drop_statements(names):
                conn.execute(text(statement))
    finally:
        engine.dispose()


def _drop_stale_worker_databases(base_url: str) -> None:
    """Startup cleanup (one worker only): stale copies left by runs that died."""
    own_base = make_url(base_url).database or ""
    try:
        engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as conn:
                names = list(conn.execute(text("SELECT datname FROM pg_database")).scalars())
        finally:
            engine.dispose()
        _drop_databases(base_url, stale_worker_databases(names, datetime.now(UTC), own_base))
    except SQLAlchemyError as exc:
        _cleanup_problem("stale worker databases not dropped", exc)


def _ensure_database(base_url: str, url: str) -> None:
    """Create the worker database (via the base test DB) if it does not exist yet."""
    if url == base_url:
        return
    name = make_url(url).database or ""
    if not SAFE_DB_NAME.fullmatch(name):
        raise ValueError(f"unsafe worker database name: {name!r}")
    engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).first()
            if exists is None:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


TEST_DATABASE_URL: str = worker_database_url(
    BASE_TEST_DATABASE_URL, os.environ.get("PYTEST_XDIST_WORKER")
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="tj-test-logs-")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="tj-test-data-")
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
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    try:
        if worker in (None, "", "gw0"):
            _drop_stale_worker_databases(BASE_TEST_DATABASE_URL)
        _ensure_database(BASE_TEST_DATABASE_URL, TEST_DATABASE_URL)
    except (SQLAlchemyError, ValueError) as exc:
        orig = getattr(exc, "orig", exc)
        name = make_url(TEST_DATABASE_URL).database
        pytest.exit(f"Could not create the worker test database {name}: {orig}", returncode=3)
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
    name = make_url(TEST_DATABASE_URL).database or ""
    if TEST_DATABASE_URL != BASE_TEST_DATABASE_URL and run_stamp(name) is not None:
        try:
            _drop_databases(BASE_TEST_DATABASE_URL, [name])  # one-off run: leave nothing behind
        except SQLAlchemyError as exc:
            _cleanup_problem(f"worker database {name} not dropped", exc)


def reset_journal_requirements(engine: Engine) -> None:
    """Back to "never synced": empty journal_field_requirements, marker initial_fill_at NULL.
    The first sync of the test then stamps 1970 (every required field applies)."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM journal_field_requirements"))
        conn.execute(text("UPDATE journal_requirements_state SET initial_fill_at = NULL"))


@pytest.fixture(autouse=True)
def _fresh_journal_requirements(request: pytest.FixtureRequest) -> None:
    """Tests that use the DB start with the required-since table in its post-migration
    state, so the result never depends on what an earlier test synced."""
    if "db_engine" in request.fixturenames:
        reset_journal_requirements(request.getfixturevalue("db_engine"))


@pytest.fixture(autouse=True)
def _protected_paths_untouched() -> Iterator[None]:
    """Fail the test if it wrote (or tried to write) a protected repo path, even when the
    code under test swallowed the guard's exception."""
    GUARD.take()
    yield
    if blocked := GUARD.take():
        pytest.fail("Test wrote a protected repo path: " + "; ".join(blocked), pytrace=False)


@pytest.fixture(autouse=True)
def _no_native_pg_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real native PostgreSQL under %PROGRAMFILES% must not leak into tests that fake
    `shutil.which`; tests of app.system.pg_tools pass `program_files` explicitly."""
    from app.system import pg_tools

    monkeypatch.setattr(pg_tools, "default_program_files", lambda: None)


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
    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as test_client:
        yield test_client

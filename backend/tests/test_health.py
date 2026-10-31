from __future__ import annotations

import re
import time
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import db as app_db
from tests.conftest import TEST_DATABASE_URL

ISO_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert ISO_UTC_Z.match(body["time_utc"])
    assert body["db"]["ok"] is True
    assert body["db"]["error"] is None
    assert isinstance(body["db"]["latency_ms"], int)
    assert body["db"]["latency_ms"] >= 0


def _unreachable_url() -> str:
    # Port 1 on loopback: nothing listens there, connection is refused/timed out.
    url = make_url(TEST_DATABASE_URL).set(host="127.0.0.1", port=1)
    return url.render_as_string(hide_password=False)


def test_health_degraded_when_db_unreachable(app: FastAPI) -> None:
    bad_engine = app_db.make_engine(_unreachable_url())
    bad_factory = app_db.make_session_factory(bad_engine)

    def _bad_db() -> Iterator[Session]:
        session = bad_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[app_db.get_db] = _bad_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            started = time.perf_counter()
            response = client.get("/api/health")
            elapsed = time.perf_counter() - started
    finally:
        bad_engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"]["ok"] is False
    assert body["db"]["error"].startswith("Database is not reachable")
    assert isinstance(body["db"]["latency_ms"], int)
    # connect_timeout is 2 s; allow headroom for slow CI machines.
    assert elapsed < 5, f"health took {elapsed:.2f}s"
    # Never leak connection details.
    url = make_url(TEST_DATABASE_URL)
    raw = response.text
    assert "postgresql" not in raw
    assert "127.0.0.1" not in raw
    assert url.password is None or str(url.password) not in raw

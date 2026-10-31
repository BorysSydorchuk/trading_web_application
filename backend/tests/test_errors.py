from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.errors import ApiError


class _Item(BaseModel):
    name: str
    qty: int


def _add_test_routes(app: FastAPI) -> None:
    router = APIRouter(prefix="/api/_test")

    @router.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("secret internal detail")

    @router.get("/http")
    def http_error() -> dict[str, str]:
        raise HTTPException(status_code=409, detail="Already exists")

    @router.get("/api-error")
    def api_error() -> dict[str, str]:
        raise ApiError(400, "custom_code", "Custom message", {"x": 1})

    @router.get("/db-down")
    def db_down() -> dict[str, str]:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    @router.post("/items")
    def create_item(item: _Item, limit: int = 10) -> dict[str, Any]:
        return {"name": item.name, "limit": limit}

    app.include_router(router)


@pytest.fixture
def client_with_routes(app: FastAPI, client: TestClient) -> TestClient:
    _add_test_routes(app)
    return client


def _assert_envelope(body: dict[str, Any], code: str) -> dict[str, Any]:
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert error["message"]
    return error


def test_unknown_route_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    error = _assert_envelope(response.json(), "not_found")
    assert error["details"] is None


def test_method_not_allowed_envelope(client: TestClient) -> None:
    response = client.post("/api/health")
    assert response.status_code == 405
    _assert_envelope(response.json(), "method_not_allowed")


def test_http_exception_envelope(client_with_routes: TestClient) -> None:
    response = client_with_routes.get("/api/_test/http")
    assert response.status_code == 409
    error = _assert_envelope(response.json(), "conflict")
    assert error["message"] == "Already exists"


def test_api_error_envelope(client_with_routes: TestClient) -> None:
    response = client_with_routes.get("/api/_test/api-error")
    assert response.status_code == 400
    error = _assert_envelope(response.json(), "custom_code")
    assert error["details"] == {"x": 1}


def test_validation_error_envelope(client_with_routes: TestClient) -> None:
    response = client_with_routes.post("/api/_test/items?limit=abc", json={"qty": "not-a-number"})
    assert response.status_code == 422
    error = _assert_envelope(response.json(), "validation_error")
    fields = error["details"]["fields"]
    assert set(fields) == {"name", "qty", "limit"}
    assert all(isinstance(v, str) and v for v in fields.values())


def test_validation_error_missing_body(client_with_routes: TestClient) -> None:
    response = client_with_routes.post("/api/_test/items")
    assert response.status_code == 422
    error = _assert_envelope(response.json(), "validation_error")
    assert error["details"]["fields"]


def test_db_operational_error_returns_503(client_with_routes: TestClient) -> None:
    response = client_with_routes.get("/api/_test/db-down")
    assert response.status_code == 503
    _assert_envelope(response.json(), "db_unavailable")
    assert "connection refused" not in response.text


def test_unhandled_exception_returns_500_envelope_and_logs(
    client_with_routes: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.errors"):
        response = client_with_routes.get("/api/_test/boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    error = _assert_envelope(response.json(), "internal_error")
    assert "secret internal detail" not in response.text
    assert error["details"] is None

    records = [r for r in caplog.records if r.name == "app.errors"]
    assert records, "unhandled error was not logged"
    assert records[-1].exc_info is not None
    assert "/api/_test/boom" in records[-1].getMessage()

"""Browser trust boundary: reject remote-origin actions before endpoint side effects."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def probe() -> tuple[FastAPI, list[str]]:
    app = create_app()
    calls: list[str] = []

    @app.api_route("/audit-probe", methods=["GET", "POST", "PATCH", "DELETE"])
    def endpoint() -> dict[str, bool]:
        calls.append("called")
        return {"ok": True}

    return app, calls


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "localhost.evil.example",
        "user@localhost",
        "localhost:bad",
        "localhost/path",
        "localhost:0",
    ],
)
def test_foreign_or_malformed_host_rejected_before_endpoint(
    probe: tuple[FastAPI, list[str]], host: str
) -> None:
    app, calls = probe
    response = TestClient(app, base_url="http://127.0.0.1:5173").get(
        "/audit-probe", headers={"Host": host, "X-Forwarded-Host": "localhost"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://user@127.0.0.1:5173",
        "http://127.0.0.1:5173/path",
        "http://127.0.0.1:5173?secret=synthetic",
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_foreign_origin_cannot_read_or_trigger_local_actions(
    probe: tuple[FastAPI, list[str]], origin: str, method: str
) -> None:
    app, calls = probe
    response = TestClient(app, base_url="http://127.0.0.1:5173").request(
        method, "/audit-probe", headers={"Origin": origin}
    )
    assert response.status_code == 403
    assert calls == []
    assert response.json()["error"] == {
        "code": "forbidden",
        "message": "Local same-origin requests only",
        "details": None,
    }


@pytest.mark.parametrize("host", ["127.0.0.1:5173", "localhost:5173", "[::1]:5173"])
def test_same_origin_vite_proxy_and_native_health_clients_work(
    probe: tuple[FastAPI, list[str]], host: str
) -> None:
    app, calls = probe
    api = TestClient(app, base_url="http://" + host)
    assert (
        api.post(
            "/audit-probe", headers={"Origin": "http://" + host, "Sec-Fetch-Site": "same-origin"}
        ).status_code
        == 200
    )
    assert api.get("/audit-probe").status_code == 200
    assert calls == ["called", "called"]


@pytest.mark.parametrize(
    "headers",
    [
        [("Host", "127.0.0.1:5173"), ("Host", "evil.example")],
        [("Origin", "http://127.0.0.1:5173"), ("Origin", "https://evil.example")],
        [("Sec-Fetch-Site", "cross-site")],
    ],
)
def test_ambiguous_or_cross_site_browser_headers_fail_closed(
    probe: tuple[FastAPI, list[str]], headers: list[tuple[str, str]]
) -> None:
    app, calls = probe
    response = TestClient(app, base_url="http://127.0.0.1:5173").post(
        "/audit-probe", headers=headers
    )
    assert response.status_code == 403
    assert calls == []


def test_api_responses_deny_embedding_and_mime_sniffing(probe: tuple[FastAPI, list[str]]) -> None:
    app, _ = probe
    response = TestClient(app, base_url="http://127.0.0.1").get("/audit-probe")
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("x-content-type-options") == "nosniff"

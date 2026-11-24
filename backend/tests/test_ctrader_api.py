"""cTrader API: OAuth callback, accounts, PATCH limits, and secrets absent from every answer."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api.ctrader import get_deps
from app.config import Settings
from app.ctrader import protocol as p
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.state import OAuthStateStore
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.logging_setup import LOG_FORMAT, UTCFormatter
from app.models import Account, SyncLog
from app.services.ctrader import CtraderDeps
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    CTID,
    REFRESH_TOKEN,
    TRADER_LOGIN,
    FakeConnector,
    FakeTransport,
    account_list_payload,
    default_handlers,
    make_ctrader_account,
    make_mt5_account,
)

CODE = "one-time-code-synthetic"
NAVIGATION = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}
SECRETS = (ACCESS_TOKEN, REFRESH_TOKEN, CLIENT_SECRET, CODE)


def _token_body() -> dict[str, Any]:
    return {
        "accessToken": ACCESS_TOKEN,
        "tokenType": "bearer",
        "expiresIn": 2628000,
        "refreshToken": REFRESH_TOKEN,
        "errorCode": None,
        "description": None,
    }


class Harness:
    def __init__(self, data_dir: Path) -> None:
        self.settings = Settings(
            _env_file=None,
            database_url="postgresql://unused",
            ctrader_client_id=CLIENT_ID,
            ctrader_client_secret=SecretStr(CLIENT_SECRET),
            data_dir=data_dir,
        )
        self.store = TokenStore(tokens_path(data_dir))
        self.states = OAuthStateStore()
        self.handlers = default_handlers()
        self.token_body: dict[str, Any] | Exception = _token_body()
        self.http_calls = 0

    def http(self, _method: str, _url: str, _params: dict[str, str]) -> dict[str, Any]:
        self.http_calls += 1
        if isinstance(self.token_body, Exception):
            raise self.token_body
        return self.token_body

    def deps(self) -> CtraderDeps:
        connector = FakeConnector(FakeTransport(self.handlers))
        return CtraderDeps(self.settings, self.store, self.states, self.http, connector)

    def connect_tokens(self) -> None:
        now = datetime.now(UTC)
        self.store.write(
            TokenPair(
                SecretStr(ACCESS_TOKEN), SecretStr(REFRESH_TOKEN), now + timedelta(days=30), now
            )
        )


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    db = make_session_factory(db_engine)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def harness(app: FastAPI, tmp_path: Path) -> Harness:
    built = Harness(tmp_path)
    app.dependency_overrides[get_deps] = built.deps
    return built


def _callback(client: TestClient, **params: str) -> Any:
    return client.get(
        "/api/ctrader/callback", params=params, headers=NAVIGATION, follow_redirects=False
    )


def _state(client: TestClient) -> str:
    url = client.post("/api/ctrader/connect").json()["authorize_url"]
    return str(parse_qs(urlsplit(url).query)["state"][0])


def _assert_error_redirect(response: Any, code: str) -> None:
    assert response.status_code == 302
    location = response.headers["location"]
    assert location == f"http://127.0.0.1:5173/settings?ctrader_error={code}"


def _account_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ctid_trader_account_id": CTID,
        "name": "cTrader One",
        "firm": "Firm",
        "program": "Program",
        "phase": "phase_1",
        "starting_balance": "1000.00",
        "currency": "USD",
        "daily_loss_pct": "5.00",
    }
    return body | overrides


# --- status / connect -------------------------------------------------------------------


def test_status_not_configured(client: TestClient, app: FastAPI, harness: Harness) -> None:
    empty = replace(
        harness.deps(),
        settings=harness.settings.model_copy(
            update={"ctrader_client_id": "", "ctrader_client_secret": SecretStr("")}
        ),
    )
    app.dependency_overrides[get_deps] = lambda: empty
    body = client.get("/api/ctrader/status").json()
    assert body == {"configured": False, "connected": False, "error_code": "not_configured"}
    answer = client.post("/api/ctrader/connect")
    assert answer.status_code == 503
    assert answer.json()["error"]["code"] == "ctrader_not_configured"
    assert client.get("/api/ctrader/accounts").json()["error"]["code"] == "ctrader_not_configured"


def test_status_flow(client: TestClient, harness: Harness) -> None:
    assert client.get("/api/ctrader/status").json() == {
        "configured": True,
        "connected": False,
        "error_code": None,
    }
    harness.connect_tokens()
    assert client.get("/api/ctrader/status").json()["connected"] is True


def test_status_reports_an_expired_token(client: TestClient, harness: Harness) -> None:
    now = datetime.now(UTC)
    harness.store.write(
        TokenPair(SecretStr("a"), SecretStr("r"), now - timedelta(days=1), now - timedelta(days=31))
    )
    assert client.get("/api/ctrader/status").json() == {
        "configured": True,
        "connected": False,
        "error_code": "token_expired",
    }


def test_status_reports_a_damaged_token_file(client: TestClient, harness: Harness) -> None:
    harness.store.path.write_text("broken", encoding="utf-8")
    body = client.get("/api/ctrader/status").json()
    assert (body["connected"], body["error_code"]) == (False, "token_invalid")


def test_status_shows_token_error_recorded_after_the_token(
    client: TestClient, harness: Harness, session: Session
) -> None:
    harness.connect_tokens()
    account = make_ctrader_account(session)
    session.add(
        SyncLog(
            account_id=account.id,
            started_at=datetime.now(UTC) + timedelta(seconds=1),
            ok=False,
            error_code="token_invalid",
        )
    )
    session.commit()
    body = client.get("/api/ctrader/status").json()
    assert (body["connected"], body["error_code"]) == (False, "token_invalid")


def test_old_token_error_does_not_hide_a_new_connection(
    client: TestClient, harness: Harness, session: Session
) -> None:
    account = make_ctrader_account(session)
    session.add(
        SyncLog(
            account_id=account.id,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            ok=False,
            error_code="token_invalid",
        )
    )
    session.commit()
    harness.connect_tokens()
    assert client.get("/api/ctrader/status").json()["connected"] is True


def test_connect_returns_a_view_scope_url(client: TestClient, harness: Harness) -> None:
    url = client.post("/api/ctrader/connect").json()["authorize_url"]
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["accounts"]
    assert query["client_id"] == [CLIENT_ID]
    assert CLIENT_SECRET not in url


# --- callback ---------------------------------------------------------------------------


def test_callback_success_stores_tokens_and_redirects(client: TestClient, harness: Harness) -> None:
    response = _callback(client, code=CODE, state=_state(client))
    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:5173/settings?ctrader=connected"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    saved = harness.store.read()
    assert saved is not None
    assert saved.access_token.get_secret_value() == ACCESS_TOKEN


def test_callback_redirect_never_holds_a_secret(client: TestClient, harness: Harness) -> None:
    response = _callback(client, code=CODE, state=_state(client))
    for secret in SECRETS:
        assert secret not in response.headers["location"]
        assert secret not in response.text


@pytest.mark.parametrize("state", ["", "forged"])
def test_callback_bad_state_makes_no_exchange(
    client: TestClient, harness: Harness, state: str
) -> None:
    _state(client)
    _assert_error_redirect(_callback(client, code=CODE, state=state), "state_invalid")
    assert harness.http_calls == 0
    assert harness.store.read() is None


def test_callback_without_state(client: TestClient, harness: Harness) -> None:
    _assert_error_redirect(_callback(client, code=CODE), "state_invalid")
    assert harness.http_calls == 0


def test_callback_state_is_single_use(client: TestClient, harness: Harness) -> None:
    state = _state(client)
    _callback(client, code=CODE, state=state)
    _assert_error_redirect(_callback(client, code=CODE, state=state), "state_invalid")
    assert harness.http_calls == 1


def test_callback_provider_error_is_not_reflected(client: TestClient, harness: Harness) -> None:
    response = _callback(client, error="<script>alert(1)</script>", state=_state(client))
    _assert_error_redirect(response, "access_denied")
    assert harness.http_calls == 0


def test_forged_error_cannot_burn_a_real_state(client: TestClient, harness: Harness) -> None:
    state = _state(client)
    _callback(client, error="access_denied", state="forged")
    response = _callback(client, code=CODE, state=state)
    assert response.headers["location"].endswith("ctrader=connected")


def test_callback_without_code(client: TestClient, harness: Harness) -> None:
    _assert_error_redirect(_callback(client, state=_state(client)), "bad_response")


def test_callback_refused_exchange(client: TestClient, harness: Harness) -> None:
    harness.token_body = {"errorCode": "ACCESS_DENIED", "description": f"bad {CODE}"}
    response = _callback(client, code=CODE, state=_state(client))
    _assert_error_redirect(response, "token_invalid")
    assert harness.store.read() is None


def test_callback_exchange_timeout(client: TestClient, harness: Harness) -> None:
    harness.token_body = CtraderError(CtraderErrorCode.TIMEOUT, "slow")
    _assert_error_redirect(_callback(client, code=CODE, state=_state(client)), "timeout")


def test_callback_unexpected_error_is_a_redirect(client: TestClient, harness: Harness) -> None:
    harness.token_body = ValueError(f"boom {CLIENT_SECRET}")
    response = _callback(client, code=CODE, state=_state(client))
    _assert_error_redirect(response, "internal_error")


@pytest.mark.parametrize("scope", ["SCOPE_TRADE", 1, None])
def test_trade_scope_is_refused_and_tokens_deleted(
    client: TestClient, harness: Harness, scope: object
) -> None:
    harness.connect_tokens()  # an earlier connection is forgotten too
    harness.handlers[p.ACCOUNT_LIST_REQ] = (p.ACCOUNT_LIST_RES, account_list_payload(scope))
    response = _callback(client, code=CODE, state=_state(client))
    _assert_error_redirect(response, "trade_scope_refused")
    assert harness.store.read() is None


def test_scope_failure_stores_nothing(client: TestClient, harness: Harness) -> None:
    harness.handlers[p.ACCOUNT_LIST_REQ] = (p.ERROR_RES, {"errorCode": "CH_ACCESS_TOKEN_INVALID"})
    response = _callback(client, code=CODE, state=_state(client))
    _assert_error_redirect(response, "token_invalid")
    assert harness.store.read() is None


def test_callback_passes_the_browser_boundary_only_as_navigation(
    client: TestClient, harness: Harness
) -> None:
    state = _state(client)
    fetched = client.get(
        "/api/ctrader/callback",
        params={"code": CODE, "state": state},
        headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"},
        follow_redirects=False,
    )
    assert fetched.status_code == 403
    framed = client.get(
        "/api/ctrader/callback",
        params={"code": CODE, "state": state},
        headers={
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "iframe",
        },
        follow_redirects=False,
    )
    assert framed.status_code == 403
    assert harness.http_calls == 0


def test_boundary_exception_is_limited_to_the_callback(
    client: TestClient, harness: Harness
) -> None:
    assert client.get("/api/ctrader/status", headers=NAVIGATION).status_code == 403
    assert client.get("/api/accounts", headers=NAVIGATION).status_code == 403


def test_access_log_line_hides_the_callback_query() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        f'127.0.0.1 - "GET /api/ctrader/callback?code={CODE}&state=abc HTTP/1.1" 302',
        None,
        None,
    )
    rendered = UTCFormatter(LOG_FORMAT).format(record)
    assert CODE not in rendered
    assert "state=abc" not in rendered


# --- accounts ---------------------------------------------------------------------------


def test_list_accounts(client: TestClient, harness: Harness, session: Session) -> None:
    harness.connect_tokens()
    assert client.get("/api/ctrader/accounts").json() == {
        "items": [
            {
                "ctid_trader_account_id": CTID,
                "is_live": False,
                "trader_login": TRADER_LOGIN,
                "broker": "Demo Broker",
                "already_added": False,
            }
        ]
    }
    make_ctrader_account(session)
    assert client.get("/api/ctrader/accounts").json()["items"][0]["already_added"] is True


def test_list_without_tokens(client: TestClient, harness: Harness) -> None:
    response = client.get("/api/ctrader/accounts")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ctrader_token_invalid"


def test_list_refuses_a_token_that_became_trade_scoped(
    client: TestClient, harness: Harness
) -> None:
    harness.connect_tokens()
    harness.handlers[p.ACCOUNT_LIST_REQ] = (
        p.ACCOUNT_LIST_RES,
        account_list_payload("SCOPE_TRADE"),
    )
    response = client.get("/api/ctrader/accounts")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ctrader_trade_scope_refused"
    assert harness.store.read() is None


def test_add_account(client: TestClient, harness: Harness, session: Session) -> None:
    harness.connect_tokens()
    response = client.post("/api/ctrader/accounts", json=_account_body())
    assert response.status_code == 201
    data = response.json()
    assert data["platform"] == "ctrader"
    assert data["login"] == TRADER_LOGIN
    assert data["server"] == "Demo Broker"
    assert data["terminal_path"] is None
    assert data["reference_balance"] == "1000.00"
    assert data["password_env_key"] == ""
    assert data["password_configured"] is True
    stored = session.get(Account, data["id"])
    assert stored is not None
    assert (stored.ctid_trader_account_id, stored.ctrader_is_live) == (CTID, False)


def test_add_refuses_an_id_outside_the_grant(client: TestClient, harness: Harness) -> None:
    harness.connect_tokens()
    response = client.post(
        "/api/ctrader/accounts", json=_account_body(ctid_trader_account_id=CTID + 1)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ctrader_account_not_granted"


def test_add_refuses_a_grant_without_login(client: TestClient, harness: Harness) -> None:
    harness.connect_tokens()
    payload = account_list_payload()
    del payload["ctidTraderAccount"][0]["traderLogin"]
    harness.handlers[p.ACCOUNT_LIST_REQ] = (p.ACCOUNT_LIST_RES, payload)
    response = client.post("/api/ctrader/accounts", json=_account_body())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ctrader_account_incomplete"


def test_add_twice_is_a_conflict(client: TestClient, harness: Harness) -> None:
    harness.connect_tokens()
    assert client.post("/api/ctrader/accounts", json=_account_body()).status_code == 201
    second = client.post("/api/ctrader/accounts", json=_account_body(name="Other"))
    assert second.status_code == 409
    assert second.json()["error"]["details"]["field"] in {"ctid_trader_account_id", "login"}


@pytest.mark.parametrize(
    "extra",
    [{"platform": "mt5"}, {"login": 5}, {"server": "x"}, {"terminal_path": "x"}, {"token": "x"}],
)
def test_add_refuses_fields_that_come_from_ctrader(
    client: TestClient, harness: Harness, extra: dict[str, Any]
) -> None:
    harness.connect_tokens()
    response = client.post("/api/ctrader/accounts", json=_account_body(**extra))
    assert response.status_code == 422


def test_add_uses_the_existing_validation(client: TestClient, harness: Harness) -> None:
    harness.connect_tokens()
    response = client.post("/api/ctrader/accounts", json=_account_body(currency="usd"))
    assert response.status_code == 422


def test_forget_connection_keeps_accounts(
    client: TestClient, harness: Harness, session: Session
) -> None:
    harness.connect_tokens()
    account = make_ctrader_account(session)
    assert client.delete("/api/ctrader/connection").status_code == 204
    assert harness.store.read() is None
    assert client.get(f"/api/accounts/{account.id}").status_code == 200
    assert client.delete("/api/ctrader/connection").status_code == 204


# --- the existing accounts API ----------------------------------------------------------


def test_accounts_api_shows_the_platform(client: TestClient, session: Session) -> None:
    make_mt5_account(session)
    make_ctrader_account(session)
    platforms = {a["name"]: a["platform"] for a in client.get("/api/accounts").json()["items"]}
    assert platforms == {"MT5 Account": "mt5", "cTrader Demo": "ctrader"}


def test_patch_cannot_change_the_platform(client: TestClient, session: Session) -> None:
    account = make_mt5_account(session)
    response = client.patch(f"/api/accounts/{account.id}", json={"platform": "ctrader"})
    assert response.status_code == 422


def test_create_cannot_set_the_platform(client: TestClient) -> None:
    response = client.post(
        "/api/accounts",
        json={
            "name": "X",
            "firm": "F",
            "program": "P",
            "phase": "phase_1",
            "login": 1,
            "server": "S",
            "starting_balance": "1000.00",
            "currency": "USD",
            "platform": "ctrader",
        },
    )
    assert response.status_code == 422


def test_patch_ctrader_needs_no_terminal(client: TestClient, session: Session) -> None:
    account = make_ctrader_account(session)
    response = client.patch(
        f"/api/accounts/{account.id}",
        json={
            "name": "Renamed",
            "login": account.login,
            "server": account.server,
            "terminal_path": None,
            "reference_balance": "2000.00",
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["terminal_path"] is None


@pytest.mark.parametrize(
    "change",
    [{"login": 999}, {"server": "Other"}, {"terminal_path": "D:\\MT5\\x\\terminal64.exe"}],
)
def test_patch_refuses_ctrader_identity_changes(
    client: TestClient, session: Session, change: dict[str, Any]
) -> None:
    account = make_ctrader_account(session)
    response = client.patch(f"/api/accounts/{account.id}", json=change)
    assert response.status_code == 422
    assert next(iter(change)) in response.json()["error"]["details"]["fields"]


def test_patch_mt5_can_still_change_those_fields(client: TestClient, session: Session) -> None:
    account = make_mt5_account(session)
    response = client.patch(f"/api/accounts/{account.id}", json={"server": "New-Server"})
    assert response.status_code == 200


def test_account_response_has_no_ctrader_secret(
    client: TestClient, harness: Harness, session: Session
) -> None:
    harness.connect_tokens()
    created = client.post("/api/ctrader/accounts", json=_account_body())
    listed = client.get("/api/ctrader/accounts")
    status = client.get("/api/ctrader/status")
    for response in (created, listed, status):
        for secret in SECRETS:
            assert secret not in response.text
    assert Decimal(created.json()["starting_balance"]) == Decimal("1000.00")

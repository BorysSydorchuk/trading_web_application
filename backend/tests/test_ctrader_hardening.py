"""Review fixes: consistent equity, error routing, outages, refresh safety, cadence, guards."""

from __future__ import annotations

import ast
import asyncio
import http.client
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app as app_package
from app.ctrader import errors, guard, oauth, reader
from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.money import parse_int, to_stored
from app.ctrader.reader import BalanceRead, Credentials, read_balance, read_balances
from app.ctrader.token_manager import REFUSED_COOLDOWN, TokenManager
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import SyncLog
from app.worker.ctrader_job import CtraderJobConfig, run_ctrader_balance_cycle
from tests.conftest import alembic_config
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    CTID,
    REFRESH_TOKEN,
    FakeConnector,
    FakeTransport,
    default_handlers,
    make_ctrader_account,
    make_mt5_account,
    no_sleep,
)

CREDS = Credentials(CLIENT_ID, SecretStr(CLIENT_SECRET), SecretStr(ACCESS_TOKEN))
TRADING = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)  # Monday 13:00 Brussels
IDLE = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)  # Sunday
APP_DIR = Path(app_package.__file__).resolve().parent


def _trader(balance: int, ctid: int = CTID) -> tuple[int, dict[str, Any]]:
    return (
        p.TRADER_RES,
        {"ctidTraderAccountId": ctid, "trader": {"balance": balance, "moneyDigits": 2}},
    )


def _handlers_for(*ctids: int) -> dict[int, Any]:
    handlers = default_handlers()

    def auth(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return p.ACCOUNT_AUTH_RES, {"ctidTraderAccountId": frame["payload"]["ctidTraderAccountId"]}

    def trader(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return _trader(100050, frame["payload"]["ctidTraderAccountId"])

    def pnl(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        ctid = frame["payload"]["ctidTraderAccountId"]
        return p.POSITION_PNL_RES, {"ctidTraderAccountId": ctid, "moneyDigits": 2}

    assert ctids
    handlers[p.ACCOUNT_AUTH_REQ] = auth
    handlers[p.TRADER_REQ] = trader
    handlers[p.POSITION_PNL_REQ] = pnl
    return handlers


def _read(transport: FakeTransport) -> BalanceRead:
    async def scenario() -> BalanceRead:
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=no_sleep)
        await connection.start()
        try:
            return await read_balance(connection, CREDS, CTID)
        finally:
            await connection.close()

    return asyncio.run(scenario())


# --- 1. equity consistency --------------------------------------------------------------


def test_balance_change_mid_read_is_retried() -> None:
    balances = iter([100000, 100050, 100050, 100050])
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = lambda _frame: _trader(next(balances))
    transport = FakeTransport(handlers)
    result = _read(transport)
    assert result.balance == Decimal("1000.50")
    assert result.equity == Decimal("1012.84")
    assert transport.types_sent().count(p.TRADER_REQ) == 4
    assert transport.types_sent().count(p.POSITION_PNL_REQ) == 2


def test_balance_that_keeps_changing_gives_no_equity() -> None:
    balances = iter([100000, 100010, 100020, 100030])
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = lambda _frame: _trader(next(balances))
    result = _read(FakeTransport(handlers))
    assert result.equity is None
    assert result.balance == Decimal("1000.30")
    assert result.equity_error == "balance_changed"


def test_read_order_is_balance_pnl_balance() -> None:
    transport = FakeTransport()
    _read(transport)
    reads = [t for t in transport.types_sent() if t in (p.TRADER_REQ, p.POSITION_PNL_REQ)]
    assert reads == [p.TRADER_REQ, p.POSITION_PNL_REQ, p.TRADER_REQ]


# --- 2. error routing -------------------------------------------------------------------


def test_stray_error_frame_does_not_fail_an_in_flight_request() -> None:
    handlers: dict[int, Any] = {p.TRADER_REQ: None}
    transport = FakeTransport(handlers)

    async def scenario() -> dict[str, Any]:
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=no_sleep)
        await connection.start()
        try:
            pending = asyncio.create_task(connection.request(p.TRADER_REQ, {}, p.TRADER_RES))
            await asyncio.sleep(0.01)
            transport.push(p.ERROR_RES, {"errorCode": "SOMETHING_NEW"}, "not-a-pending-id")
            await asyncio.sleep(0.01)
            assert not pending.done()
            transport.push(p.TRADER_RES, {"ok": True}, transport.sent[0]["clientMsgId"])
            return await pending
        finally:
            await connection.close()

    assert asyncio.run(scenario()) == {"ok": True}


def test_error_without_id_still_fails_pending() -> None:
    transport = FakeTransport({p.TRADER_REQ: None})

    async def scenario() -> None:
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=no_sleep)
        await connection.start()
        try:
            pending = asyncio.create_task(connection.request(p.TRADER_REQ, {}, p.TRADER_RES))
            await asyncio.sleep(0.01)
            transport.push(p.ERROR_RES, {"errorCode": "ACCOUNT_NOT_AUTHORIZED"})
            await pending
        finally:
            await connection.close()

    with pytest.raises(CtraderError) as caught:
        asyncio.run(scenario())
    assert caught.value.code is CtraderErrorCode.NOT_AUTHORIZED


# --- 3. isolation between environments, parse limits ------------------------------------


def test_unexpected_failure_of_one_environment_keeps_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = reader._read_environment

    async def flaky(
        creds: Credentials, is_live: bool, ctids: Any, *args: Any, **kwargs: Any
    ) -> dict[int, BalanceRead | CtraderError]:
        if is_live:
            raise ValueError("bug")
        return await real(creds, is_live, ctids, *args, **kwargs)

    monkeypatch.setattr(reader, "_read_environment", flaky)
    demo = FakeTransport(_handlers_for(1))

    async def connector(_url: str) -> FakeTransport:
        return demo

    results = asyncio.run(read_balances(CREDS, [(1, False), (2, True)], connector, sleep=no_sleep))
    assert isinstance(results[1], BalanceRead)
    failed = results[2]
    assert isinstance(failed, CtraderError)
    assert failed.code is CtraderErrorCode.INTERNAL_ERROR


@pytest.mark.parametrize("value", ["1" * 21, "-" + "1" * 21, "9" * 5000, 2**64, -(2**64)])
def test_parse_int_caps_the_length(value: object) -> None:
    with pytest.raises(CtraderError) as caught:
        parse_int(value, "balance")
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


def test_parse_int_accepts_the_largest_uint64() -> None:
    assert parse_int(str(2**64 - 1), "x") == 2**64 - 1


# --- 4. to_stored -----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "1E+100", "1E+999999"])
def test_to_stored_never_leaks_invalid_operation(value: str) -> None:
    with pytest.raises(CtraderError) as caught:
        to_stored(Decimal(value))
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


# --- 5. outages and the time cap --------------------------------------------------------


def test_failed_reconnect_stops_the_environment() -> None:
    handlers = _handlers_for(1, 2)
    first = FakeTransport(handlers)

    def drop(_frame: dict[str, Any]) -> None:
        first.push_raw(OSError("socket closed"))

    handlers[p.TRADER_REQ] = drop
    first.handlers = handlers
    connector = FakeConnector(first, OSError("down"))
    results = asyncio.run(read_balances(CREDS, [(1, False), (2, False)], connector, sleep=no_sleep))
    for ctid in (1, 2):
        result = results[ctid]
        assert isinstance(result, CtraderError)
        assert result.code is CtraderErrorCode.CONNECTION_FAILED
    assert len(connector.urls) == 4  # the first connect + one reconnect of 3 attempts


def test_time_cap_keeps_finished_accounts() -> None:
    handlers = _handlers_for(1, 2)
    good = handlers[p.TRADER_REQ]

    def trader(frame: dict[str, Any]) -> Any:
        return None if frame["payload"]["ctidTraderAccountId"] == 2 else good(frame)

    handlers[p.TRADER_REQ] = trader
    transport = FakeTransport(handlers)

    async def connector(_url: str) -> FakeTransport:
        return transport

    results = asyncio.run(
        read_balances(CREDS, [(1, False), (2, False)], connector, sleep=no_sleep, budget_s=0.1)
    )
    assert isinstance(results[1], BalanceRead)
    capped = results[2]
    assert isinstance(capped, CtraderError)
    assert capped.code is CtraderErrorCode.TIMEOUT
    assert transport.closed


# --- DB fixtures ------------------------------------------------------------------------


@pytest.fixture
def clean_db(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def factory(db_engine: Engine, clean_db: None) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


@pytest.fixture
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _pair(at: datetime, days: int = 30, access: str = ACCESS_TOKEN) -> TokenPair:
    return TokenPair(SecretStr(access), SecretStr(REFRESH_TOKEN), at + timedelta(days=days), at)


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    token_store = TokenStore(tokens_path(tmp_path))
    token_store.write(_pair(TRADING))
    return token_store


def _config(store: TokenStore, connector: Any, at: datetime, **extra: Any) -> CtraderJobConfig:
    return CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=connector,
        sleep=no_sleep,
        now=lambda: at,
        **extra,
    )


def _log_count(session: Session, account_id: int) -> int:
    session.expire_all()
    return len(list(session.scalars(select(SyncLog).where(SyncLog.account_id == account_id))))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1E+100"])
def test_corrupt_value_is_recorded_and_writes_nothing(
    session: Session, factory: sessionmaker[Session], store: TokenStore, value: str
) -> None:
    account = make_ctrader_account(session, balance=Decimal("900.00"))

    async def corrupt(_creds: Any, targets: Any, *_args: Any, **_kwargs: Any) -> Any:
        return {ctid: BalanceRead(Decimal(value), Decimal(value)) for ctid, _live in targets}

    config = _config(store, FakeConnector(FakeTransport()), TRADING, read=corrupt)
    assert run_ctrader_balance_cycle(factory, config) == []
    session.refresh(account)
    assert account.balance == Decimal("900.00")
    log = session.scalars(select(SyncLog).where(SyncLog.account_id == account.id)).one()
    assert (log.ok, log.error_code) == (False, "bad_response")


def test_job_passes_a_time_budget_below_its_interval(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    make_ctrader_account(session)
    seen: dict[str, Any] = {}

    async def capture(_creds: Any, targets: Any, *_args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return {ctid: BalanceRead(Decimal(1), Decimal(1)) for ctid, _live in targets}

    run_ctrader_balance_cycle(
        factory, _config(store, FakeConnector(FakeTransport()), TRADING, read=capture)
    )
    assert 0 < seen["budget_s"] < 60


# --- 6. PATCH terminal path -------------------------------------------------------------


def test_patch_blank_terminal_on_null_is_no_change(
    client: TestClient, session: Session, clean_db: None
) -> None:
    account = make_ctrader_account(session)
    response = client.patch(f"/api/accounts/{account.id}", json={"terminal_path": ""})
    assert response.status_code == 200


def test_patch_null_terminal_on_a_stored_blank_is_no_change(
    client: TestClient, session: Session, clean_db: None
) -> None:
    account = make_ctrader_account(session, terminal_path="")
    response = client.patch(f"/api/accounts/{account.id}", json={"terminal_path": None})
    assert response.status_code == 200


# --- 7. partial unique index ------------------------------------------------------------


def test_two_ctrader_accounts_may_share_login_and_broker(session: Session) -> None:
    make_ctrader_account(session)
    make_ctrader_account(session, name="Second", ctid_trader_account_id=CTID + 1)


def test_ctrader_account_may_share_login_and_server_with_mt5(session: Session) -> None:
    mt5 = make_mt5_account(session)
    make_ctrader_account(session, login=mt5.login, server=mt5.server)


def test_mt5_duplicates_are_still_refused_by_the_database(session: Session) -> None:
    make_mt5_account(session)
    with pytest.raises(IntegrityError):
        make_mt5_account(session, name="Other")
    session.rollback()


def _mt5_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Dup",
        "firm": "F",
        "program": "P",
        "phase": "phase_1",
        "login": 90000001,
        "server": "Broker-Server",
        "starting_balance": "1000.00",
        "currency": "USD",
    }
    return body | overrides


def test_mt5_duplicate_keeps_the_clear_409_on_post_and_patch(
    client: TestClient, session: Session
) -> None:
    make_mt5_account(session)
    posted = client.post("/api/accounts", json=_mt5_body())
    assert posted.status_code == 409
    assert posted.json()["error"]["details"] == {"field": "login"}
    other = make_mt5_account(session, name="Other", login=90000002)
    patched = client.patch(f"/api/accounts/{other.id}", json={"login": 90000001})
    assert patched.status_code == 409
    assert patched.json()["error"]["details"] == {"field": "login"}


def test_downgrade_restores_the_constraint(db_engine: Engine, clean_db: None) -> None:
    cfg = alembic_config()
    try:
        command.downgrade(cfg, "e7c41b9a2d60")
        names = {c["name"] for c in inspect(db_engine).get_unique_constraints("accounts")}
        assert "uq_accounts_login_server" in names
    finally:
        command.upgrade(cfg, "head")
    inspector = inspect(db_engine)
    assert "uq_accounts_login_server" not in {
        c["name"] for c in inspector.get_unique_constraints("accounts")
    }
    assert "uq_accounts_mt5_login_server" in {i["name"] for i in inspector.get_indexes("accounts")}


def test_downgrade_error_warns_about_trades(session: Session) -> None:
    make_ctrader_account(session)
    session.commit()
    cfg = alembic_config()
    try:
        with pytest.raises(RuntimeError, match="trades"):
            command.downgrade(cfg, "e7c41b9a2d60")
    finally:
        command.upgrade(cfg, "head")


# --- 8. refresh safety ------------------------------------------------------------------


def _token_body(access: str = "new-access", refresh: str = "new-refresh") -> dict[str, Any]:
    return {
        "accessToken": access,
        "tokenType": "bearer",
        "expiresIn": 2628000,
        "refreshToken": refresh,
        "errorCode": None,
        "description": None,
    }


class CountingHttp:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.calls = 0

    def __call__(self, _method: str, _url: str, _params: dict[str, str]) -> dict[str, Any]:
        self.calls += 1
        return self.body


def _manager(store: TokenStore, http: Any, at: datetime) -> TokenManager:
    return TokenManager(store, CLIENT_ID, SecretStr(CLIENT_SECRET), http=http, now=lambda: at)


def _fail_writes(monkeypatch: pytest.MonkeyPatch, store: TokenStore) -> list[int]:
    attempts: list[int] = []

    def fail(_pair: TokenPair) -> None:
        attempts.append(1)
        raise CtraderError(CtraderErrorCode.TOKEN_STORE_FAILED, "disk full")

    monkeypatch.setattr(store, "write", fail)
    return attempts


def test_failed_write_is_retried_and_the_new_pair_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    attempts = _fail_writes(monkeypatch, store)
    http = CountingHttp(_token_body())
    token = _manager(store, http, TRADING).fresh_access_token()
    assert token.get_secret_value() == "new-access"
    assert len(attempts) >= 2


def test_unsaved_pair_survives_and_is_saved_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    _fail_writes(monkeypatch, store)
    http = CountingHttp(_token_body())
    _manager(store, http, TRADING).fresh_access_token()
    monkeypatch.undo()
    later = TRADING + timedelta(minutes=1)
    token = _manager(TokenStore(store.path), http, later).fresh_access_token()
    assert token.get_secret_value() == "new-access"
    assert http.calls == 1  # the single-use refresh token was not spent again
    saved = store.read()
    assert saved is not None
    assert saved.refresh_token.get_secret_value() == "new-refresh"


def test_forgetting_the_connection_drops_an_unsaved_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    _fail_writes(monkeypatch, store)
    _manager(store, CountingHttp(_token_body()), TRADING).fresh_access_token()
    monkeypatch.undo()
    store.delete()
    with pytest.raises(CtraderError) as caught:
        _manager(store, CountingHttp(_token_body()), TRADING).fresh_access_token()
    assert caught.value.code is CtraderErrorCode.TOKEN_INVALID
    assert store.read() is None


def test_a_newer_connection_replaces_an_unsaved_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    _fail_writes(monkeypatch, store)
    _manager(store, CountingHttp(_token_body()), TRADING).fresh_access_token()
    monkeypatch.undo()
    later = TRADING + timedelta(hours=1)
    store.write(_pair(later, access="reconnected"))
    token = _manager(store, CountingHttp(_token_body()), later).fresh_access_token()
    assert token.get_secret_value() == "reconnected"


def test_refused_refresh_cools_down(tmp_path: Path) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    http = CountingHttp({"errorCode": "INVALID_GRANT", "description": "used"})
    for minutes in (0, 1, 30):
        with pytest.raises(CtraderError) as caught:
            _manager(store, http, TRADING + timedelta(minutes=minutes)).fresh_access_token()
        assert caught.value.code is CtraderErrorCode.TOKEN_INVALID
        assert "reconnect" in caught.value.message.lower()
    assert http.calls == 1
    after = TRADING + REFUSED_COOLDOWN + timedelta(seconds=1)
    with pytest.raises(CtraderError):
        _manager(store, http, after).fresh_access_token()
    assert http.calls == 2


def test_a_new_connection_ends_the_cooldown(tmp_path: Path) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    refused = CountingHttp({"errorCode": "INVALID_GRANT", "description": "used"})
    with pytest.raises(CtraderError):
        _manager(store, refused, TRADING).fresh_access_token()
    later = TRADING + timedelta(minutes=5)
    store.write(_pair(later, days=1))
    good = CountingHttp(_token_body())
    assert _manager(store, good, later).fresh_access_token().get_secret_value() == "new-access"
    assert good.calls == 1


@pytest.mark.parametrize(
    "failure", [http.client.IncompleteRead(b""), http.client.BadStatusLine("x")]
)
def test_http_protocol_errors_are_connection_failed(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def fake_open(_request: Any, timeout: float) -> Any:
        assert timeout
        raise failure

    monkeypatch.setattr(oauth, "_open_url", fake_open)
    with pytest.raises(CtraderError) as caught:
        oauth.call_token_endpoint("GET", oauth.TOKEN_URL, {"client_secret": CLIENT_SECRET})
    assert caught.value.code is CtraderErrorCode.CONNECTION_FAILED
    assert CLIENT_SECRET not in str(caught.value)


def test_delete_retries_a_locked_file(store: TokenStore, monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path.unlink
    calls: list[int] = []

    def flaky(path: Path, missing_ok: bool = False) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("in use")
        real(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky)
    store.delete()
    monkeypatch.undo()
    assert len(calls) == 2
    assert store.read() is None


def test_delete_that_keeps_failing_is_a_typed_error(
    store: TokenStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(_path: Path, missing_ok: bool = False) -> None:
        raise PermissionError(f"in use {missing_ok}")

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(CtraderError) as caught:
        store.delete()
    monkeypatch.undo()
    assert caught.value.code is CtraderErrorCode.TOKEN_STORE_FAILED


# --- 9. cadence -------------------------------------------------------------------------


def test_trading_hours_cadence_is_sixty_seconds(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport()), TRADING))
    idle_connector = FakeConnector(FakeTransport())
    soon = TRADING + timedelta(seconds=20)
    assert run_ctrader_balance_cycle(factory, _config(store, idle_connector, soon)) == []
    assert idle_connector.urls == []
    assert _log_count(session, account.id) == 1
    run_ctrader_balance_cycle(
        factory,
        _config(store, FakeConnector(FakeTransport()), TRADING + timedelta(seconds=60)),
    )
    assert _log_count(session, account.id) == 2


def test_idle_cadence_follows_the_rules(
    session: Session, factory: sessionmaker[Session], tmp_path: Path
) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(IDLE))
    account = make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport()), IDLE))
    run_ctrader_balance_cycle(
        factory, _config(store, FakeConnector(FakeTransport()), IDLE + timedelta(minutes=5))
    )
    assert _log_count(session, account.id) == 1
    run_ctrader_balance_cycle(
        factory, _config(store, FakeConnector(FakeTransport()), IDLE + timedelta(minutes=15))
    )
    assert _log_count(session, account.id) == 2


def test_broken_rules_skip_the_cycle_without_a_connection(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    from app.config_files import ConfigError

    make_ctrader_account(session)

    def broken() -> Any:
        raise ConfigError(Path("rules.yaml"), ["broken"])

    connector = FakeConnector(FakeTransport())
    config = _config(store, connector, TRADING, rules_getter=broken)
    assert run_ctrader_balance_cycle(factory, config) == []
    assert connector.urls == []


def test_broken_firms_skip_the_cycle_without_a_connection(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.config_files import ConfigError

    make_ctrader_account(session)

    def broken() -> Any:
        raise ConfigError(Path("firms.yaml"), ["broken"])

    connector = FakeConnector(FakeTransport())
    config = _config(store, connector, TRADING, firms_getter=broken)
    assert run_ctrader_balance_cycle(factory, config) == []
    assert connector.urls == []
    assert "cTrader sync skipped" in caplog.text


# --- 10. send surface -------------------------------------------------------------------


def test_refresh_message_is_not_allowed() -> None:
    assert 2173 not in guard.ALLOWED_OUTGOING
    assert 2124 in guard.ALLOWED_OUTGOING
    with pytest.raises(guard.ForbiddenMessageError):
        guard.assert_allowed(2173)


def _socket_uses(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "open_websocket":
                found.append("calls open_websocket")
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "send"
                and isinstance(func.value, ast.Attribute | ast.Name)
                and getattr(func.value, "attr", getattr(func.value, "id", ""))
                in {"transport", "_transport", "_socket", "socket"}
            ):
                found.append("writes to the transport")
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            if any(n.split(".")[0] == "websockets" for n in names):
                found.append("imports websockets")
    return found


def test_only_connection_touches_the_socket() -> None:
    hits = {
        str(path.relative_to(APP_DIR)): uses
        for path in APP_DIR.rglob("*.py")
        if path.name != "connection.py" or path.parent.name != "ctrader"
        if (uses := _socket_uses(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert hits == {}


def test_the_scan_detects_a_write() -> None:
    assert _socket_uses(ast.parse("async def f(self):\n    await self._transport.send('x')\n"))
    assert _socket_uses(ast.parse("open_websocket('wss://x')\n"))


def test_websockets_logger_never_logs_frames() -> None:
    assert logging.getLogger("websockets").level >= logging.INFO


# --- code-reviewer 2026-11-24 ------------------------------------------------------------------


def test_a_token_invalidated_during_the_pnl_read_is_not_an_equity_error() -> None:
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (p.ERROR_RES, {"errorCode": "CH_ACCESS_TOKEN_INVALID"})
    transport = FakeTransport(handlers)

    async def body() -> BalanceRead:
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=no_sleep)
        await connection.start()
        try:
            return await read_balance(connection, CREDS, CTID)
        finally:
            await connection.close()

    with pytest.raises(CtraderError) as caught:
        asyncio.run(body())
    assert caught.value.code is CtraderErrorCode.TOKEN_INVALID


def test_a_secret_cut_at_the_length_limit_is_still_masked() -> None:
    error = errors.error_from_server("X", "a" * 195 + ACCESS_TOKEN, None, secrets=[ACCESS_TOKEN])
    assert ACCESS_TOKEN[:5] not in error.message


def test_a_refused_token_description_is_masked_before_it_is_cut(tmp_path: Path) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    http = CountingHttp({"errorCode": "INVALID_GRANT", "description": "a" * 195 + REFRESH_TOKEN})
    with pytest.raises(CtraderError) as caught:
        oauth.refresh_tokens(
            SecretStr(REFRESH_TOKEN), CLIENT_ID, SecretStr(CLIENT_SECRET), http=http, now=TRADING
        )
    assert REFRESH_TOKEN[:5] not in caught.value.message


def test_a_login_beyond_bigint_is_treated_as_missing() -> None:
    account = reader._parse_account({"ctidTraderAccountId": CTID, "traderLogin": 2**63})
    assert account.trader_login is None


def test_a_broken_refresh_answer_cools_down_too(tmp_path: Path) -> None:
    store = TokenStore(tokens_path(tmp_path))
    store.write(_pair(TRADING, days=1))
    http = CountingHttp({"errorCode": None})
    with pytest.raises(CtraderError) as first:
        _manager(store, http, TRADING).fresh_access_token()
    assert first.value.code is CtraderErrorCode.BAD_RESPONSE
    with pytest.raises(CtraderError) as second:
        _manager(store, http, TRADING + timedelta(minutes=1)).fresh_access_token()
    assert second.value.code is CtraderErrorCode.TOKEN_INVALID
    assert http.calls == 1

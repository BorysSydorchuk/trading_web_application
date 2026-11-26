"""The cTrader balance job: stores good reads, never overwrites with a failed one."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.sync_status import utc_now
from app.config import get_settings
from app.ctrader import protocol as p
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import Account, SyncLog
from app.services.firm_day import floating as _floating
from app.worker.ctrader_job import CtraderJobConfig, run_ctrader_balance_cycle
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REFRESH_TOKEN,
    FakeConnector,
    FakeTransport,
    default_handlers,
    make_ctrader_account,
    make_mt5_account,
    no_sleep,
)

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


@pytest.fixture
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    token_store = TokenStore(tokens_path(tmp_path))
    token_store.write(
        TokenPair(SecretStr(ACCESS_TOKEN), SecretStr(REFRESH_TOKEN), NOW + timedelta(days=30), NOW)
    )
    return token_store


def _config(store: TokenStore, connector: Any, **overrides: Any) -> CtraderJobConfig:
    values: dict[str, Any] = {
        "client_id": CLIENT_ID,
        "client_secret": SecretStr(CLIENT_SECRET),
        "store": store,
        "connector": connector,
        "sleep": no_sleep,
        "now": lambda: NOW,
    }
    return CtraderJobConfig(**(values | overrides))


def _logs(session: Session, account_id: int) -> list[SyncLog]:
    session.expire_all()
    return list(
        session.scalars(
            select(SyncLog).where(SyncLog.account_id == account_id).order_by(SyncLog.id)
        )
    )


def _with_good_values(session: Session, account: Account) -> None:
    account.balance = Decimal("900.00")
    account.equity = Decimal("905.00")
    account.balance_synced_at = NOW - timedelta(minutes=1)
    session.commit()


def test_success_writes_balance_equity_and_log(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    done = run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport())))
    assert done == [account.id]
    session.refresh(account)
    assert account.balance == Decimal("1000.50")
    assert account.equity == Decimal("1012.84")
    assert account.balance_synced_at == NOW
    log = _logs(session, account.id)[-1]
    assert (log.ok, log.error_code) == (True, None)
    assert log.finished_at == NOW


def test_no_ctrader_account_means_no_connection(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    make_mt5_account(session)
    connector = FakeConnector(FakeTransport())
    assert run_ctrader_balance_cycle(factory, _config(store, connector)) == []
    assert connector.urls == []


@pytest.mark.parametrize("status", ["passed", "failed", "archived"])
def test_inactive_account_is_not_read(
    session: Session, factory: sessionmaker[Session], store: TokenStore, status: str
) -> None:
    make_ctrader_account(session, status=status)
    connector = FakeConnector(FakeTransport())
    assert run_ctrader_balance_cycle(factory, _config(store, connector)) == []
    assert connector.urls == []


def test_mt5_account_is_never_touched(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    mt5 = make_mt5_account(session, balance=Decimal("5.00"))
    make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport())))
    session.refresh(mt5)
    assert mt5.balance == Decimal("5.00")
    assert _logs(session, mt5.id) == []


def test_failed_balance_read_keeps_the_good_values(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    _with_good_values(session, account)
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = (p.ERROR_RES, {"errorCode": "ACCOUNT_NOT_AUTHORIZED"})
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport(handlers))))
    session.refresh(account)
    assert account.balance == Decimal("900.00")
    assert account.equity == Decimal("905.00")
    assert account.balance_synced_at == NOW - timedelta(minutes=1)
    log = _logs(session, account.id)[-1]
    assert (log.ok, log.error_code) == (False, "not_authorized")


def test_failed_equity_keeps_the_balance_and_equity_pair(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    """Home computes floating P&L as equity - balance: a half-updated pair would lie."""
    account = make_ctrader_account(session)
    _with_good_values(session, account)
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (p.ERROR_RES, {"errorCode": "SOMETHING_NEW"})
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport(handlers))))
    session.refresh(account)
    assert account.balance == Decimal("900.00")
    assert account.equity == Decimal("905.00")
    assert account.balance_synced_at == NOW - timedelta(minutes=1)
    log = _logs(session, account.id)[-1]
    assert (log.ok, log.error_code) == (False, "equity_unavailable")


def test_failed_equity_on_first_read_stores_balance_without_inventing_equity(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (p.ERROR_RES, {"errorCode": "SOMETHING_NEW"})
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport(handlers))))
    session.refresh(account)
    assert account.balance == Decimal("1000.50")
    assert account.equity is None
    assert _logs(session, account.id)[-1].error_code == "equity_unavailable"


def test_value_too_large_is_refused(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    _with_good_values(session, account)
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = (
        p.TRADER_RES,
        {"trader": {"balance": 9223372036854775807, "moneyDigits": 0}},
    )
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport(handlers))))
    session.refresh(account)
    assert account.balance == Decimal("900.00")
    assert _logs(session, account.id)[-1].error_code == "bad_response"


def test_not_configured_is_recorded(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    connector = FakeConnector(FakeTransport())
    run_ctrader_balance_cycle(factory, _config(store, connector, client_id=""))
    assert connector.urls == []
    assert _logs(session, account.id)[-1].error_code == "not_configured"


def test_missing_tokens_are_token_invalid(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    store.delete()
    connector = FakeConnector(FakeTransport())
    run_ctrader_balance_cycle(factory, _config(store, connector))
    assert connector.urls == []
    assert _logs(session, account.id)[-1].error_code == "token_invalid"


def test_connection_failure_is_recorded_per_account(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(OSError("down"))))
    assert _logs(session, account.id)[-1].error_code == "connection_failed"


def test_unexpected_error_is_recorded_and_does_not_escape(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)

    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("unexpected")

    config = _config(store, FakeConnector(FakeTransport()), read=boom)
    assert run_ctrader_balance_cycle(factory, config) == []
    assert _logs(session, account.id)[-1].error_code == "internal_error"


def test_job_logs_no_secret(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    account = make_ctrader_account(session)
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = (
        p.ERROR_RES,
        {"errorCode": "X", "description": f"oops {ACCESS_TOKEN} {CLIENT_SECRET}"},
    )
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport(handlers))))
    stored = _logs(session, account.id)[-1].error_message or ""
    for secret in (ACCESS_TOKEN, CLIENT_SECRET, REFRESH_TOKEN):
        assert secret not in caplog.text
        assert secret not in stored


def _sync_row(client: TestClient, now: datetime) -> dict[str, Any]:
    client.app.dependency_overrides[utc_now] = lambda: now  # type: ignore[attr-defined]
    try:
        return dict(client.get("/api/sync/status").json()["items"][0])
    finally:
        client.app.dependency_overrides.pop(utc_now)  # type: ignore[attr-defined]


def test_sync_status_shows_a_ctrader_success(
    client: TestClient, session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport())))
    row = _sync_row(client, NOW + timedelta(seconds=30))
    assert row["state"] == "ok"
    assert row["error_code"] is None


def test_sync_status_is_stale_after_three_ctrader_intervals(
    client: TestClient, session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport())))
    assert _sync_row(client, NOW + timedelta(seconds=180))["state"] == "ok"
    assert _sync_row(client, NOW + timedelta(seconds=181))["state"] == "stale"


@pytest.mark.parametrize(
    ("server_code", "state", "code"),
    [
        ("BLOCKED_PAYLOAD_TYPE", "warning", "rate_limited"),
        ("ACCOUNT_NOT_AUTHORIZED", "error", "not_authorized"),
        ("CH_ACCESS_TOKEN_INVALID", "error", "token_invalid"),
    ],
)
def test_sync_status_maps_ctrader_codes(
    client: TestClient,
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    server_code: str,
    state: str,
    code: str,
) -> None:
    make_ctrader_account(session)
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = (p.ERROR_RES, {"errorCode": server_code})
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport(handlers))))
    row = _sync_row(client, NOW + timedelta(seconds=30))
    assert (row["state"], row["error_code"]) == (state, code)


def test_home_uses_ctrader_balance_without_a_terminal(
    client: TestClient, session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session, daily_loss_pct=Decimal("5"))
    run_ctrader_balance_cycle(
        factory,
        _config(store, FakeConnector(FakeTransport()), now=lambda: datetime.now(UTC)),
    )
    response = client.get("/api/home", params={"account_id": account.id})
    assert response.status_code == 200
    listed = client.get(f"/api/accounts/{account.id}").json()
    assert listed["platform"] == "ctrader"
    assert listed["balance"] == "1000.50"
    assert listed["equity"] == "1012.84"
    assert listed["terminal_path"] is None


def test_test_runs_have_no_ctrader_credentials() -> None:
    assert get_settings().ctrader_configured is False


def test_home_floating_pnl_comes_from_the_ctrader_pair(
    session: Session, factory: sessionmaker[Session], store: TokenStore
) -> None:
    account = make_ctrader_account(session)
    run_ctrader_balance_cycle(factory, _config(store, FakeConnector(FakeTransport())))
    session.refresh(account)
    assert _floating(account, True, NOW + timedelta(seconds=30)) == (Decimal("12.34"), True)

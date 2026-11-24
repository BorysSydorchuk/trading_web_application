"""MT5 stays exactly as it was: no MT5 path ever opens a terminal for a cTrader account."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, text
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import get_rules
from app.config_files.symbols import get_symbols_config
from app.db import make_session_factory
from app.models import Account, SyncLog
from app.models.calculator import CalculatorMarginRequest
from app.mt5.source import Mt5Source
from app.tools import backfill_excursions as backfill
from app.tools import trade_check
from app.worker import sync_job
from app.worker.margin_job import UNSUPPORTED_PLATFORM, run_margin_cycle
from tests.ctrader_fakes import make_ctrader_account, make_mt5_account

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


class NoTerminal:
    """Any use of this MT5 source fails the test."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"MT5 source used: {name}")


def _no_terminal() -> Mt5Source:
    return cast(Mt5Source, NoTerminal())


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


def test_sync_job_selects_only_mt5_accounts(
    session: Session, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    mt5 = make_mt5_account(session)
    make_ctrader_account(session)
    seen: list[int] = []

    def fake_sync(_session: Session, account: Account, *_args: Any, **_kwargs: Any) -> None:
        seen.append(account.id)

    monkeypatch.setattr(sync_job, "sync_account", fake_sync)
    synced = sync_job._sync_due_accounts(
        factory, _no_terminal(), get_rules(), get_symbols_config(), lambda: NOW
    )
    assert seen == [mt5.id]
    assert synced == [mt5.id]


def _queue_margin(session: Session, account_id: int) -> int:
    row = CalculatorMarginRequest(
        account_id=account_id,
        symbol="EURUSD",
        broker_symbol="EURUSD",
        direction="buy",
        volume=Decimal("1"),
        entry=Decimal("1.1"),
        currency="USD",
        status="pending",
        expires_at=func.now() + timedelta(minutes=5),
    )
    session.add(row)
    session.commit()
    return row.id


def test_margin_job_never_opens_a_terminal_for_ctrader(
    session: Session, factory: sessionmaker[Session]
) -> None:
    account = make_ctrader_account(session)
    request_id = _queue_margin(session, account.id)
    handled = run_margin_cycle(factory, _no_terminal(), threading.Lock())
    assert handled == request_id
    session.expire_all()
    row = session.get(CalculatorMarginRequest, request_id)
    assert row is not None
    assert (row.status, row.error_code) == ("failed", UNSUPPORTED_PLATFORM)


def test_margin_request_api_refuses_ctrader(client: TestClient, session: Session) -> None:
    account = make_ctrader_account(session)
    response = client.post(
        "/api/calculator/margin-requests",
        json={
            "account_id": account.id,
            "symbol": "EURUSD",
            "direction": "buy",
            "entry": "1.1",
            "sl_points": "10",
            "risk_percent": "1",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "margin_unsupported_platform"


def test_backfill_skips_ctrader_accounts(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    mt5 = make_mt5_account(session)
    make_ctrader_account(session)
    seen: list[int] = []

    def fake(_session: Session, account: Account, *_args: Any, **_kwargs: Any) -> None:
        seen.append(account.id)

    monkeypatch.setattr(backfill, "backfill_account", fake)
    monkeypatch.setattr(backfill, "worker_running", lambda *_args: False)
    backfill.run(session, _no_terminal(), NOW, apply=False)
    assert seen == [mt5.id]


def test_backfill_with_a_ctrader_id_does_nothing(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = make_ctrader_account(session)

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("must not run")

    monkeypatch.setattr(backfill, "backfill_account", fail)
    monkeypatch.setattr(backfill, "worker_running", lambda *_args: False)
    backfill.run(session, _no_terminal(), NOW, apply=False, account_id=account.id)


def test_same_broker_terminals_never_offer_a_ctrader_account(session: Session) -> None:
    own = make_mt5_account(session, firm="Same")
    make_ctrader_account(
        session, firm="Same", server=own.server, login=5, terminal_path="D:\\x\\terminal64.exe"
    )
    assert backfill.same_broker_terminals(session, own) == []


def test_trade_check_does_not_connect_for_ctrader(session: Session) -> None:
    account = make_ctrader_account(session)
    report = trade_check.build_report(session, str(account.id), 5, _no_terminal(), now=NOW)
    assert report.blocks == []


def test_mt5_row_defaults_are_unchanged(session: Session) -> None:
    account = make_mt5_account(session)
    session.refresh(account)
    assert (account.platform, account.ctid_trader_account_id, account.ctrader_is_live) == (
        "mt5",
        None,
        None,
    )


def test_ctrader_failure_row_does_not_affect_mt5_due_check(
    session: Session, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_mt5_account(session)
    ctrader = make_ctrader_account(session)
    session.add(SyncLog(account_id=ctrader.id, started_at=NOW, finished_at=NOW, ok=False))
    session.commit()
    seen: list[int] = []

    def fake_sync(_session: Session, account: Account, *_args: Any, **_kwargs: Any) -> None:
        seen.append(account.id)

    monkeypatch.setattr(sync_job, "sync_account", fake_sync)
    sync_job._sync_due_accounts(
        factory, _no_terminal(), get_rules(), get_symbols_config(), lambda: NOW
    )
    assert ctrader.id not in seen
    assert len(seen) == 1

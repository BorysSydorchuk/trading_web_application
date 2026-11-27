"""Initial SL from the cTrader order history (2183) through the worker job. Fixture JSON only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.trades import apply_initial_sl
from app.ctrader import guard
from app.ctrader import protocol as p
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import Account, Trade
from app.services import open_positions_snapshot as snapshot
from app.worker.ctrader_job import CtraderJobConfig, run_ctrader_balance_cycle
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REFRESH_TOKEN,
    FakeConnector,
    FakeTransport,
    make_ctrader_account,
    no_sleep,
)
from tests.ctrader_history_fakes import HistoryServer, load
from tests.symbols_fixture import TEST_SYMBOLS

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
ENTRY_MS = 1795424400000  # closed_simple.json entry deal (orderId 8001), buy at 1.08512


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


@pytest.fixture
def account(session: Session) -> Account:
    return make_ctrader_account(session, reference_balance=Decimal("1000.00"))


def _run(
    factory: sessionmaker[Session], store: TokenStore, server: HistoryServer, tmp_path: Path
) -> None:
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(server.transport()),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
        snapshot_path=snapshot.snapshot_path(tmp_path),
    )
    run_ctrader_balance_cycle(factory, config)


def _trade(session: Session, position_id: int) -> Trade:
    session.expire_all()
    return session.scalars(select(Trade).where(Trade.position_id == position_id)).one()


def _opening_order(**extra: Any) -> dict[str, Any]:
    return {
        "orderId": 8001,
        "positionId": 5001,
        "orderType": "MARKET",
        "orderStatus": "ORDER_STATUS_FILLED",
        "executionPrice": 1.08512,
        "utcLastUpdateTimestamp": ENTRY_MS,
        "closingOrder": False,
        "tradeData": {
            "symbolId": 1,
            "volume": 1000000,
            "tradeSide": "BUY",
            "openTimestamp": ENTRY_MS - 100,
        },
        **extra,
    }


def test_closed_trade_never_seen_open_gets_its_sl_from_the_opening_order(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    # relativeStopLoss 100 = 0.00100 below the execution price
    server = HistoryServer(
        load("closed_simple.json")["deals"], orders=[_opening_order(relativeStopLoss=100)]
    )
    _run(factory, store, server, tmp_path)
    trade = _trade(session, 5001)
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("1.08412"), "order")
    assert trade.status == "needs_description"
    assert trade.risk_amount is not None
    assert trade.r_multiple is not None
    assert server.order_requests == [5001]


def test_no_stop_in_the_order_history_still_asks_for_the_sl(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(load("closed_simple.json")["deals"], orders=[_opening_order()])
    _run(factory, store, server, tmp_path)
    trade = _trade(session, 5001)
    assert (trade.status, trade.initial_sl, trade.initial_sl_source) == ("needs_sl", None, None)


def test_a_user_entered_sl_is_never_overwritten(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    deals = load("closed_simple.json")["deals"]
    _run(factory, store, HistoryServer(deals), tmp_path)
    trade = _trade(session, 5001)
    apply_initial_sl(session, trade, Decimal("1.08300"))
    session.commit()

    server = HistoryServer(deals, orders=[_opening_order(relativeStopLoss=100)])
    _run(factory, store, server, tmp_path)
    trade = _trade(session, 5001)
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("1.08300"), "user")
    assert server.order_requests == []  # stored with an SL: never read again


def test_a_position_seen_open_reads_no_order_history(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("closed_simple.json")
    entry, _ = data["deals"]
    _run(
        factory,
        store,
        HistoryServer([entry], [data["open_position"]], [data["open_pnl"]]),
        tmp_path,
    )
    closing = HistoryServer(data["deals"], orders=[_opening_order(relativeStopLoss=500)])
    _run(factory, store, closing, tmp_path)
    trade = _trade(session, 5001)
    assert closing.order_requests == []
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("1.08412"), "position")

    # Next sync: closed in the DB, still inside the overlap window.
    again = HistoryServer(data["deals"], orders=[_opening_order(relativeStopLoss=500)])
    _run(factory, store, again, tmp_path)
    trade = _trade(session, 5001)
    assert again.order_requests == []
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("1.08412"), "position")


def test_only_read_only_messages_are_sent(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(
        load("closed_simple.json")["deals"], orders=[_opening_order(relativeStopLoss=100)]
    )
    transport = server.transport()
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(transport),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
        snapshot_path=snapshot.snapshot_path(tmp_path),
    )
    run_ctrader_balance_cycle(factory, config)
    sent = set(transport.types_sent())
    assert 2183 in sent
    assert sent <= guard.ALLOWED_OUTGOING
    assert not sent & guard.BLOCKED_OUTGOING


def test_a_failing_order_read_keeps_the_deals(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(load("closed_simple.json")["deals"])
    handlers = server.handlers()
    handlers[p.ORDER_LIST_BY_POSITION_REQ] = (
        p.ERROR_RES,
        {"errorCode": "SERVER_IS_UNDER_MAINTENANCE", "description": "down"},
    )
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(FakeTransport(handlers), FakeTransport(handlers)),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
        snapshot_path=snapshot.snapshot_path(tmp_path),
    )
    run_ctrader_balance_cycle(factory, config)
    trade = _trade(session, 5001)
    assert (trade.status, trade.initial_sl) == ("needs_sl", None)


def _protective(stop: float) -> dict[str, Any]:
    return {
        "orderId": 8003,
        "positionId": 5001,
        "orderType": "STOP_LOSS_TAKE_PROFIT",
        "orderStatus": "ORDER_STATUS_CANCELLED",
        "closingOrder": True,
        "stopPrice": stop,
        "utcLastUpdateTimestamp": ENTRY_MS + 1000,
        "tradeData": {
            "symbolId": 1,
            "volume": 1000000,
            "tradeSide": "SELL",
            "openTimestamp": ENTRY_MS,
        },
    }


@pytest.mark.parametrize(("stop", "flagged"), [(1.08300, True), (1.08412, False), (1.08500, False)])
def test_a_stop_moved_away_after_entry_is_a_violation(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    stop: float,
    flagged: bool,
) -> None:
    """Initial SL 1.08412 (buy at 1.08512): moved away to 1.08300 is flagged; the same stop or
    one moved toward the entry (1.08500) never is (no_breakeven covers the entry itself)."""
    server = HistoryServer(
        load("closed_simple.json")["deals"],
        orders=[_opening_order(relativeStopLoss=100), _protective(stop)],
    )
    _run(factory, store, server, tmp_path)
    trade = _trade(session, 5001)
    assert trade.initial_sl == Decimal("1.08412")
    assert trade.last_sl == Decimal(str(stop)).quantize(Decimal("0.00001"))
    keys = {v.rule_key for v in trade.rule_violations}
    assert ("sl_moved_away" in keys) is flagged


def test_the_moved_stop_survives_a_re_read_in_the_overlap_window(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    deals = load("closed_simple.json")["deals"]
    first = HistoryServer(deals, orders=[_opening_order(relativeStopLoss=100), _protective(1.083)])
    _run(factory, store, first, tmp_path)
    again = HistoryServer(deals, orders=[_opening_order(relativeStopLoss=100), _protective(1.083)])
    _run(factory, store, again, tmp_path)  # same deals: closed in the DB, inside the overlap

    trade = _trade(session, 5001)
    assert again.order_requests == []  # known SL: not read again
    assert (trade.initial_sl, trade.last_sl) == (Decimal("1.08412"), Decimal("1.08300"))
    assert "sl_moved_away" in {v.rule_key for v in trade.rule_violations}

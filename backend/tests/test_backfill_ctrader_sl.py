"""`app.tools.backfill_ctrader_sl`: selection, dry run, apply, never over an owner SL."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.ctrader import guard
from app.ctrader import protocol as p
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import ms_from_utc
from app.ctrader.orders import CtOrder
from app.ctrader.reader import Credentials
from app.db import make_session_factory
from app.models import Account, Trade
from app.tools.backfill_ctrader_sl import read_orders, run, summary, targets
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    CTID,
    FakeConnector,
    FakeTransport,
    default_handlers,
    make_ctrader_account,
    make_mt5_account,
)

OPEN = datetime(2026, 11, 24, 8, 55, tzinfo=UTC)
CLOSE = OPEN + timedelta(minutes=5)


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


def _trade(session: Session, account: Account, position_id: int, **kw: Any) -> Trade:
    values: dict[str, Any] = {
        "account_id": account.id,
        "position_id": position_id,
        "symbol": "GER40",
        "direction": "buy",
        "open_time": OPEN,
        "close_time": CLOSE,
        "entry_price": Decimal("25266.6"),
        "exit_price": Decimal("25276.6"),
        "volume": Decimal("1"),
        "gross_pnl": Decimal("10"),
        "net_pnl": Decimal("10"),
        "status": "needs_sl",
        "mfe_price": Decimal("25286.6"),
        "mae_price": Decimal("25256.6"),
        "excursion_status": "final",
    }
    trade = Trade(**(values | kw))
    session.add(trade)
    session.commit()
    return trade


def _order(order_id: int, **kw: Any) -> CtOrder:
    values: dict[str, Any] = {
        "order_id": order_id,
        "position_id": 1,
        "kind": "market",
        "side": "buy",
        "filled": True,
        "closing": False,
        "created": OPEN,
        "execution_price": Decimal("25266.6"),
        "stop_loss": None,
        "relative_stop_loss": 2_000_000,  # 20.0 below
        "stop_price": None,
    }
    return CtOrder(**(values | kw))


def test_targets_are_closed_ctrader_trades_without_any_sl(session: Session) -> None:
    ct = make_ctrader_account(session, reference_balance=Decimal("100000"))
    mt5 = make_mt5_account(session)
    wanted = _trade(session, ct, 1)
    _trade(session, ct, 2, initial_sl=Decimal("25200"), initial_sl_source="user")
    _trade(session, ct, 3, close_time=None, status="open")
    _trade(session, mt5, 4)
    found = targets(session)
    assert [t.trade_id for t in found] == [wanted.id]
    assert found[0].start < OPEN
    assert found[0].end > CLOSE
    assert (found[0].ctid, found[0].side) == (CTID, "buy")


def test_dry_run_writes_nothing(session: Session) -> None:
    account = make_ctrader_account(session, reference_balance=Decimal("100000"))
    trade = _trade(session, account, 1)
    todo = targets(session)
    totals = run(session, {trade.id: (_order(10),)}, todo, apply=False)
    session.expire_all()
    assert trade.initial_sl is None
    assert (totals.found, totals.stored) == (1, 0)
    assert "SL 25246.6 (opening, ордер 10)" in totals.lines[0]
    assert "dry run" in summary(totals, False, len(todo))


def test_apply_stores_the_sl_as_order_and_recomputes_r(session: Session) -> None:
    account = make_ctrader_account(session, reference_balance=Decimal("100000"))
    trade = _trade(session, account, 1)
    totals = run(session, {trade.id: (_order(10),)}, targets(session), apply=True)
    session.expire_all()
    assert totals.stored == 1
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("25246.6"), "order")
    assert trade.status == "needs_description"
    assert trade.mfe_r == Decimal("1.0000")  # 20 / 20
    assert trade.mae_r == Decimal("0.5000")  # 10 / 20


def test_apply_never_writes_over_an_sl_set_meanwhile(session: Session) -> None:
    account = make_ctrader_account(session, reference_balance=Decimal("100000"))
    trade = _trade(session, account, 1)
    todo = targets(session)
    trade.initial_sl, trade.initial_sl_source = Decimal("25200"), "user"
    session.commit()
    totals = run(session, {trade.id: (_order(10),)}, todo, apply=True)
    session.expire_all()
    assert totals.stored == 0
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("25200.00000000"), "user")


def test_no_stop_and_read_errors_are_counted(session: Session) -> None:
    account = make_ctrader_account(session, reference_balance=Decimal("100000"))
    a, b, c = (_trade(session, account, pid) for pid in (1, 2, 3))
    error = CtraderError(CtraderErrorCode.BAD_RESPONSE, "x")
    read: dict[int, tuple[CtOrder, ...] | CtraderError] = {
        a.id: (_order(10, relative_stop_loss=None),),
        b.id: error,
    }
    totals = run(session, read, targets(session), apply=True)
    assert (totals.none, totals.failed, totals.stored) == (1, 2, 0)
    assert "помилки: 2" in summary(totals, True, 3)
    del c


def test_read_orders_authorizes_each_account_once_and_sends_only_allowed_types(
    session: Session,
) -> None:
    account = make_ctrader_account(session, reference_balance=Decimal("100000"))
    first, second = _trade(session, account, 1), _trade(session, account, 2)

    def orders(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        pid = int(frame["payload"]["positionId"])
        raw = {
            "orderId": 100 + pid,
            "positionId": pid,
            "orderType": "MARKET",
            "orderStatus": "ORDER_STATUS_FILLED",
            "utcLastUpdateTimestamp": ms_from_utc(OPEN),
            "tradeData": {"tradeSide": "BUY", "openTimestamp": ms_from_utc(OPEN)},
        }
        return p.ORDER_LIST_BY_POSITION_RES, {
            "ctidTraderAccountId": CTID,
            "order": [raw],
            "hasMore": False,
        }

    handlers = default_handlers()
    handlers[p.ORDER_LIST_BY_POSITION_REQ] = orders
    transport = FakeTransport(handlers)
    creds = Credentials(CLIENT_ID, SecretStr(CLIENT_SECRET), SecretStr(ACCESS_TOKEN))
    got = asyncio.run(read_orders(creds, targets(session), FakeConnector(transport)))
    assert {k: [o.order_id for o in v] for k, v in got.items() if isinstance(v, tuple)} == {
        first.id: [101],
        second.id: [102],
    }
    sent = transport.types_sent()
    assert sent.count(p.ACCOUNT_AUTH_REQ) == 1
    assert set(sent) <= guard.ALLOWED_OUTGOING

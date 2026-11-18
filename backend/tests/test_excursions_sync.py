"""M8-16: MAE / MFE computed in the account sync from MT5 price history (fixture source).

Server time = UTC + 3 h (EEST, October). EURUSD point 0.00001.
"""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import Account, Trade
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from tests.test_exit_reason_sync import EURUSD
from tests.test_sync import WEEK_LOGIN, add_account, run, trades_by_pid

D = Decimal
OFFSET_S = 3 * 3600
OPEN = 1792486800  # server 2026-10-20 09:00:00 = 06:00 UTC
SHORT_PID, LONG_PID, SELL_PID, OPEN_PID = 5000001, 5000002, 5000003, 5000004
SPEC = deepcopy(EURUSD) | {"point": "0.00001"}


def deal(ticket: int, pid: int, t: int, entry: int, kind: int, price: str) -> dict[str, Any]:
    return {
        "ticket": ticket,
        "order": ticket,
        "position_id": pid,
        "time": t,
        "time_msc": t * 1000,
        "type": kind,
        "entry": entry,
        "reason": 0,
        "volume": "1",
        "price": price,
        "profit": "0",
        "commission": "0",
        "swap": "0",
        "fee": "0",
        "symbol": "EURUSD",
        "sl": "1.162" if (kind == 0 and entry == 0) or (kind == 1 and entry == 1) else "1.168",
        "tp": "0",
    }


def ticks_at(*rows: tuple[int, str, str]) -> list[dict[str, Any]]:
    return [{"time_msc": t * 1000, "bid": bid, "ask": ask} for t, bid, ask in rows]


def data(now_server: int, *, open_position: bool = False) -> dict[str, Any]:
    """Three closed trades and (optionally) one open buy."""
    long_open, long_close = OPEN + 30, OPEN + 3 * 3600 + 30
    deals = [
        deal(1, 0, OPEN - 86400, 0, 2, "0") | {"profit": "100000", "symbol": ""},
        # SHORT_PID: buy 1.16500 SL 1.16200, 20 min -> ticks only
        deal(10, SHORT_PID, OPEN, 0, 0, "1.165"),
        deal(11, SHORT_PID, OPEN + 1200, 1, 1, "1.168"),
        # LONG_PID: buy 1.16500 SL 1.16200, 3 h -> ticks at the edges, M1 bars in between
        deal(20, LONG_PID, long_open, 0, 0, "1.165"),
        deal(21, LONG_PID, long_close, 1, 1, "1.166"),
        # SELL_PID: sell 1.16500 SL 1.16800, 3 h, measured on ask (bar ask = bid + spread)
        deal(30, SELL_PID, long_open, 0, 1, "1.165") | {"sl": "1.168"},
        deal(31, SELL_PID, long_close, 1, 0, "1.164") | {"sl": "1.168"},
    ]
    ticks = ticks_at(
        (OPEN + 60, "1.1665", "1.1666"),
        (OPEN + 300, "1.1638", "1.1639"),  # adverse 0.0012 = 0.4 R
        (OPEN + 600, "1.168", "1.16801"),  # favourable 0.003 = 1.0 R
        (OPEN + 1200, "1.168", "1.16801"),
        (long_open + 10, "1.16510", "1.16520"),
        (long_close - 10, "1.16590", "1.16600"),
    )
    bars = [
        {"time": OPEN + 60 + i * 60, "high": "1.16550", "low": "1.16450", "spread": 10}
        for i in range(1, 179)
    ]
    bars[50] = bars[50] | {"high": "1.16800", "low": "1.16450"}  # long MFE 1.0 R on bid
    bars[90] = bars[90] | {"high": "1.16590", "low": "1.16290"}  # long MAE 0.7 R
    # a bar overlapping the entry minute must never count
    bars.append({"time": OPEN, "high": "1.19000", "low": "1.10000", "spread": 10})
    positions: list[dict[str, Any]] = []
    if open_position:
        deals.append(deal(40, OPEN_PID, now_server - 600, 0, 0, "1.165"))
        ticks += ticks_at((now_server - 300, "1.1665", "1.1666"))
        positions.append(
            {
                "ticket": OPEN_PID,
                "identifier": OPEN_PID,
                "time": now_server - 600,
                "time_msc": (now_server - 600) * 1000,
                "type": 0,
                "volume": "1",
                "price_open": "1.165",
                "sl": "1.162",
                "tp": "0",
                "price_current": "1.1665",
                "profit": "150",
                "swap": "0",
                "symbol": "EURUSD",
            }
        )
    return {
        "format": 1,
        "account": {
            "login": WEEK_LOGIN,
            "server": "FundedNext-Server",
            "balance": "100000",
            "equity": "100000",
            "currency": "USD",
        },
        "ticks": {"EURUSD": now_server},
        "symbols": [SPEC],
        "deals": deals,
        "orders": [],
        "positions": positions,
        "tick_history": {"EURUSD": ticks},
        "m1_rates": {"EURUSD": bars},
    }


NOW_SERVER = OPEN + 4 * 3600
NOW = datetime.fromtimestamp(NOW_SERVER - OFFSET_S, UTC)


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
def rules() -> RulesConfig:
    return get_rules()


@pytest.fixture
def account(session: Session) -> Account:
    return add_account(session, WEEK_LOGIN)


def sync(
    session: Session, account: Account, rules: RulesConfig, source: FixtureMt5Source | None = None
) -> dict[int, Trade]:
    """Two syncs: the first creates the trades, the next one (60 s later in the worker)
    measures them (targets are read from the DB before the sync connects)."""
    src = source or FixtureMt5Source(data(NOW_SERVER))
    for _ in range(2):
        session.expire_all()
        log = run(session, account, src, rules, NOW)
        assert log.ok is True, log.error_message
    return trades_by_pid(session, account.id)


def test_a_short_trade_uses_ticks_only(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules)[SHORT_PID]

    assert (trade.excursion_status, trade.excursion_source) == ("final", "ticks")
    assert (trade.mfe_r, trade.mae_r) == (D("1.0000"), D("0.4000"))
    assert (trade.mfe_price, trade.mae_price) == (D("1.168"), D("1.1638"))
    assert (trade.mfe_points, trade.mae_points) == (D("300.0"), D("120.0"))
    assert trade.mfe_time == datetime(2026, 10, 20, 6, 10, tzinfo=UTC)  # server 09:10
    assert trade.mae_time == datetime(2026, 10, 20, 6, 5, tzinfo=UTC)


def test_a_long_trade_uses_m1_bars_and_never_the_bar_of_the_entry_minute(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules)[LONG_PID]

    assert (trade.excursion_status, trade.excursion_source) == ("final", "m1_ticks")
    assert (trade.mfe_r, trade.mae_r) == (D("1.0000"), D("0.7000"))


def test_a_short_position_is_measured_on_ask_with_the_bar_spread(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules)[SELL_PID]

    # risk 0.003; worst ask = bar high 1.16800 + 10 points (0.0001) -> 0.0031 = 1.0333 R;
    # best ask = bar low 1.16290 + 0.0001 -> 1.16300: 0.002 = 0.6667 R
    assert trade.mae_r == D("1.0333")
    assert trade.mfe_r == D("0.6667")


def test_an_open_trade_gets_running_values(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    source = FixtureMt5Source(data(NOW_SERVER, open_position=True))
    trade = sync(session, account, rules, source)[OPEN_PID]

    assert trade.excursion_status == "running"
    assert trade.mfe_r == D("0.5000")


def test_final_values_are_not_read_again(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    sync(session, account, rules)
    source = FixtureMt5Source(data(NOW_SERVER))
    session.expire_all()
    assert run(session, account, source, rules, NOW).ok is True
    trades = trades_by_pid(session, account.id)

    assert "ticks" not in source.calls
    assert "rates_m1" not in source.calls
    assert trades[SHORT_PID].excursion_status == "final"


def test_an_mt5_read_failure_never_fails_the_sync(
    session: Session, account: Account, rules: RulesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = FixtureMt5Source(data(NOW_SERVER))

    def broken(*_: Any) -> Any:
        raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "history not available")

    monkeypatch.setattr(source, "ticks", broken)
    trades = sync(session, account, rules, source)

    assert trades[SHORT_PID].excursion_status is None  # retried next sync
    assert trades[SHORT_PID].close_time is not None  # the trade itself synced


def test_no_history_marks_the_trade_unavailable(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    empty = data(NOW_SERVER) | {"tick_history": {}, "m1_rates": {}}
    trades = sync(session, account, rules, FixtureMt5Source(empty))

    assert trades[SHORT_PID].excursion_status == "unavailable"
    assert trades[SHORT_PID].mfe_r is None


def test_trades_older_than_seven_days_wait_for_the_backfill(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    later = NOW + timedelta(days=8)
    source = FixtureMt5Source(data(NOW_SERVER + 8 * 86400))
    for _ in range(2):
        session.expire_all()
        assert run(session, account, source, rules, later).ok is True

    assert trades_by_pid(session, account.id)[SHORT_PID].excursion_status is None

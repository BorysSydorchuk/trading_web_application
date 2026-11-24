"""cTrader phase b through the worker job: closed positions become trades like MT5 ones, open
positions reach Home, reconcile, cursor and inbox. Fixture JSON only, no live call."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import get_rules
from app.ctrader import protocol as p
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import Account, SyncLog, Trade, TradeExitDeal
from app.services import open_positions_snapshot as snapshot
from app.services.home import build_home
from app.services.inbox import count_inbox
from app.services.sync import history_window_start
from app.worker.ctrader_job import CtraderJobConfig, run_ctrader_balance_cycle
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REFRESH_TOKEN,
    FakeConnector,
    FakeTransport,
    make_ctrader_account,
    make_mt5_account,
    no_sleep,
)
from tests.ctrader_history_fakes import HistoryServer, load
from tests.symbols_fixture import TEST_SYMBOLS

MONDAY = datetime(2026, 11, 23, tzinfo=UTC)
NOW = MONDAY.replace(hour=12)


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
    factory: sessionmaker[Session],
    store: TokenStore,
    server: HistoryServer,
    at: datetime,
    tmp_path: Path,
) -> list[int]:
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(server.transport()),
        sleep=no_sleep,
        now=lambda: at,
        symbols_getter=lambda: TEST_SYMBOLS,
        snapshot_path=snapshot.snapshot_path(tmp_path),
    )
    return run_ctrader_balance_cycle(factory, config)


def _trade(session: Session, position_id: int) -> Trade:
    session.expire_all()
    return session.scalars(select(Trade).where(Trade.position_id == position_id)).one()


def _last_log(session: Session, account_id: int) -> SyncLog:
    session.expire_all()
    return session.scalars(
        select(SyncLog).where(SyncLog.account_id == account_id).order_by(SyncLog.id.desc())
    ).first()  # type: ignore[return-value]


def _home(session: Session, at: datetime, tmp_path: Path) -> Any:
    session.expire_all()
    return build_home(session, at, None, tmp_path)


# --- closed trades -------------------------------------------------------------------------


def test_trade_seen_open_then_closed_has_net_pnl_r_and_needs_description(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("closed_simple.json")
    entry, exit_ = data["deals"]
    opened = HistoryServer([entry], [data["open_position"]], [data["open_pnl"]])
    assert _run(factory, store, opened, MONDAY.replace(hour=10), tmp_path) == [account.id]

    trade = _trade(session, 5001)
    assert (trade.status, trade.close_time) == ("open", None)
    assert (trade.initial_sl, trade.initial_sl_source) == (Decimal("1.08412"), "position")
    assert trade.tp == Decimal("1.08812")
    live = snapshot.read_snapshot(snapshot.snapshot_path(tmp_path))[(account.id, 5001)]
    assert (live.price_current, live.pnl) == (None, Decimal("9.65"))

    trailed = dict(data["open_position"], stopLoss=1.086)
    moved = HistoryServer([entry], [trailed], [data["open_pnl"]])
    assert _run(factory, store, moved, MONDAY.replace(hour=10, minute=15), tmp_path)
    assert _trade(session, 5001).last_sl == Decimal("1.08600")

    closed = HistoryServer([entry, exit_])  # cTrader no longer reports the position
    assert _run(factory, store, closed, MONDAY.replace(hour=10, minute=35), tmp_path) == [
        account.id
    ]
    trade = _trade(session, 5001)
    assert trade.close_time == MONDAY.replace(hour=10, minute=30)
    assert (trade.symbol, trade.broker_symbol, trade.direction) == ("EURUSD", "EURUSD", "buy")
    assert (trade.volume, trade.entry_price, trade.exit_price) == (
        Decimal("0.1"),
        Decimal("1.08512"),
        Decimal("1.08712"),
    )
    assert (trade.gross_pnl, trade.commission, trade.swap, trade.net_pnl) == (
        Decimal("20.00"),
        Decimal("-0.70"),
        Decimal("0.00"),
        Decimal("19.30"),
    )
    assert trade.initial_sl == Decimal("1.08412")  # first seen SL kept after the close
    assert (trade.last_sl, trade.tp) == (Decimal("1.08600"), Decimal("1.08812"))  # not wiped
    assert trade.planned_rr == Decimal(3)  # (1.08812 - 1.08512) / (1.08512 - 1.08412)
    assert trade.risk_amount == Decimal("10.00")  # 20.00 x 0.00100 / 0.00200
    assert trade.r_multiple == Decimal("1.93")
    assert trade.pnl_pct == Decimal("1.93")  # of reference_balance 1000
    assert trade.status == "needs_description"
    assert session.scalar(select(func.count()).select_from(TradeExitDeal)) == 1
    assert count_inbox(session).needs_description == 1
    assert _home(session, MONDAY.replace(hour=10, minute=36), tmp_path).open_positions == []
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code, log.deals_fetched, log.open_positions) == (True, None, 2, 0)


def test_closed_trade_never_seen_open_asks_for_the_sl(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(load("closed_simple.json")["deals"])
    _run(factory, store, server, NOW, tmp_path)
    trade = _trade(session, 5001)
    assert (trade.status, trade.initial_sl, trade.risk_amount, trade.r_multiple) == (
        "needs_sl",
        None,
        None,
        None,
    )
    assert count_inbox(session).needs_sl == 1


def test_second_identical_read_changes_nothing(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(load("closed_simple.json")["deals"])
    _run(factory, store, server, NOW, tmp_path)
    _run(factory, store, server, NOW + timedelta(minutes=2), tmp_path)
    log = _last_log(session, account.id)
    assert (log.trades_created, log.trades_updated) == (0, 0)
    assert session.scalar(select(func.count()).select_from(Trade)) == 1


@pytest.mark.parametrize("max_rows", [None, 1])
def test_partial_close_is_one_trade_with_canonical_symbol(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    max_rows: int | None,
) -> None:
    server = HistoryServer(load("partial_close.json")["deals"], max_rows=max_rows)
    _run(factory, store, server, NOW, tmp_path)
    trade = _trade(session, 5002)
    assert (trade.symbol, trade.broker_symbol, trade.direction) == ("GER40", "DE40", "sell")
    assert (trade.volume, trade.exit_price) == (Decimal(2), Decimal("19485.5"))
    assert (trade.gross_pnl, trade.commission, trade.net_pnl) == (
        Decimal("30.00"),
        Decimal("-1.00"),
        Decimal("29.00"),
    )
    assert session.scalar(select(func.count()).select_from(TradeExitDeal)) == 2
    if max_rows is not None:  # hasMore paging was needed and every deal still arrived
        assert len(server.deal_requests) > 5


def test_commission_swap_and_fee_reach_the_trade(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    _run(factory, store, HistoryServer(load("commission_swap.json")["deals"]), NOW, tmp_path)
    trade = _trade(session, 5004)
    assert (trade.volume, trade.swap, trade.commission, trade.net_pnl) == (
        Decimal("0.5"),
        Decimal("-12.34"),
        Decimal("-3.60"),
        Decimal("259.06"),
    )
    assert session.scalar(select(func.count()).select_from(Trade)) == 1  # rejected deal ignored


def test_position_spanning_two_history_windows(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(load("two_windows.json")["deals"])
    _run(factory, store, server, NOW, tmp_path)
    trade = _trade(session, 5005)
    assert trade.open_time == datetime(2026, 11, 14, 12, tzinfo=UTC)
    assert trade.net_pnl == Decimal("94.04")
    assert all(hi - lo < p.MAX_DEAL_WINDOW_MS for lo, hi in server.deal_requests)
    assert len(server.deal_requests) == 5  # 30 days of initial history in one-week windows


# --- open positions and reconcile ------------------------------------------------------------


def test_open_position_is_on_home_with_its_pnl(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("open_position.json")
    server = HistoryServer(data["deals"], [data["position"]], [data["pnl"]])
    _run(factory, store, server, NOW, tmp_path)
    trade = _trade(session, 5003)
    assert (trade.status, trade.direction, trade.volume) == ("open", "sell", Decimal("0.2"))
    assert (trade.initial_sl, trade.tp) == (Decimal("1.09"), Decimal("1.08"))
    (position,) = _home(session, NOW + timedelta(minutes=1), tmp_path).open_positions
    assert position.trade_id == trade.id
    assert (position.pnl, position.current_price, position.close_unconfirmed) == (
        Decimal("-15.34"),
        None,
        False,
    )
    assert _last_log(session, account.id).open_positions == 1


def test_position_gone_without_a_close_deal_is_unconfirmed_not_closed(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("open_position.json")
    _run(
        factory,
        store,
        HistoryServer(data["deals"], [data["position"]], [data["pnl"]]),
        NOW,
        tmp_path,
    )
    later = NOW + timedelta(minutes=2)
    assert _run(factory, store, HistoryServer(data["deals"]), later, tmp_path) == [account.id]
    assert _trade(session, 5003).close_time is None
    (position,) = _home(session, later, tmp_path).open_positions
    assert (position.close_unconfirmed, position.pnl) == (True, None)


def test_funded_account_with_no_deals_does_not_close_open_trades(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("open_position.json")
    _run(
        factory,
        store,
        HistoryServer(data["deals"], [data["position"]], [data["pnl"]]),
        NOW,
        tmp_path,
    )
    path = snapshot.snapshot_path(tmp_path)
    written = snapshot.synced_at(path)[account.id]
    window = history_window_start(
        session, account.id, get_rules().sync, NOW + timedelta(days=1), require_deals=True
    )

    later = NOW + timedelta(minutes=2)
    empty = HistoryServer(balance=250000)  # no deal, no position: an incomplete read
    assert _run(factory, store, empty, later, tmp_path) == []

    trade = _trade(session, 5003)
    assert (trade.close_time, trade.status) == (None, "open")
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code) == (False, "history_incomplete")
    assert "5003" in (log.error_message or "")
    session.refresh(account)
    assert account.balance == Decimal("2500.00")  # the balance read still counts
    assert snapshot.synced_at(path)[account.id] == written  # snapshot not rewritten
    assert (
        history_window_start(
            session, account.id, get_rules().sync, NOW + timedelta(days=1), require_deals=True
        )
        == window
    )


def test_empty_read_never_advances_the_window(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    sync = get_rules().sync
    _run(factory, store, HistoryServer(), NOW, tmp_path)
    log = _last_log(session, account.id)
    assert (log.ok, log.deals_fetched) == (True, 0)
    later = NOW + timedelta(days=2)
    assert history_window_start(session, account.id, sync, later, require_deals=True) == (
        later - timedelta(days=sync.initial_history_days)
    )
    _run(factory, store, HistoryServer(load("closed_simple.json")["deals"]), later, tmp_path)
    assert history_window_start(session, account.id, sync, later, require_deals=True) == (
        later - timedelta(days=sync.overlap_days)
    )


def test_history_failure_keeps_the_balance_and_is_visible(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    handlers = HistoryServer(balance=123456).handlers()
    handlers[p.DEAL_LIST_REQ] = (p.ERROR_RES, {"errorCode": "SOMETHING_NEW", "description": "x"})
    transport = FakeTransport(handlers)
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(transport),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
    )
    assert run_ctrader_balance_cycle(factory, config) == []
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code) == (False, "bad_response")
    session.refresh(account)
    assert account.balance == Decimal("1234.56")


# --- isolation ---------------------------------------------------------------------------------


def test_mt5_accounts_are_untouched_by_the_ctrader_job(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    mt5 = make_mt5_account(session, balance=Decimal("5000.00"))
    _run(factory, store, HistoryServer(load("closed_simple.json")["deals"]), NOW, tmp_path)
    session.expire_all()
    assert session.get(Account, mt5.id).balance == Decimal("5000.00")  # type: ignore[union-attr]
    assert session.scalar(select(func.count()).where(SyncLog.account_id == mt5.id)) == 0
    assert session.scalar(select(func.count()).where(Trade.account_id == mt5.id)) == 0
    assert session.scalar(select(func.count()).where(Trade.account_id == account.id)) == 1
    assert mt5.id not in snapshot.synced_at(snapshot.snapshot_path(tmp_path))


# --- review fixes -------------------------------------------------------------------------------


def _window(session: Session, account_id: int, at: datetime) -> datetime:
    session.expire_all()
    return history_window_start(session, account_id, get_rules().sync, at, require_deals=True)


def test_unreported_new_position_is_not_written_and_is_a_visible_warning(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    entry = load("closed_simple.json")["deals"][0]
    assert _run(factory, store, HistoryServer([entry]), NOW, tmp_path) == [account.id]
    assert session.scalar(select(func.count()).select_from(Trade)) == 0
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code) == (True, "positions_skipped")
    assert "5001" in (log.error_message or "")
    assert "not reported" in (log.error_message or "")
    later = NOW + timedelta(days=1)
    assert _window(session, account.id, later) == later - timedelta(
        days=get_rules().sync.initial_history_days
    )  # the skipped run does not move the window


def test_skipped_position_is_a_warning_and_is_retried(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = HistoryServer(load("closed_simple.json")["deals"])
    for item in server.symbols["byId"]["symbol"]:
        item.pop("lotSize", None)
    assert _run(factory, store, server, NOW, tmp_path) == [account.id]
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code) == (True, "positions_skipped")
    assert "lot size of EURUSD unknown" in (log.error_message or "")
    assert session.scalar(select(func.count()).select_from(Trade)) == 0
    later = NOW + timedelta(days=1)
    assert _window(session, account.id, later) == later - timedelta(
        days=get_rules().sync.initial_history_days
    )
    _run(factory, store, HistoryServer(load("closed_simple.json")["deals"]), later, tmp_path)
    assert _trade(session, 5001).net_pnl == Decimal("19.30")  # retried and built
    assert _window(session, account.id, later) == later - timedelta(
        days=get_rules().sync.overlap_days
    )


def test_partial_close_of_a_reported_position_stays_open_with_its_exit(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    entry, partial, _final = load("partial_close.json")["deals"]
    position = load("open_position.json")["position"]
    position.update(positionId=5002, stopLoss=19520.0, takeProfit=19400.0)
    position["tradeData"].update(symbolId=2, volume=100, tradeSide="SELL")
    position["tradeData"]["openTimestamp"] = entry["executionTimestamp"]
    pnl = {"positionId": 5002, "grossUnrealizedPnL": 500, "netUnrealizedPnL": 450}
    _run(factory, store, HistoryServer([entry, partial], [position], [pnl]), NOW, tmp_path)
    trade = _trade(session, 5002)
    assert (trade.close_time, trade.status, trade.volume) == (None, "open", Decimal(2))
    assert (trade.gross_pnl, trade.net_pnl) == (Decimal("20.00"), Decimal("19.50"))
    assert (trade.last_sl, trade.tp) == (Decimal("19520.0"), Decimal("19400.0"))
    assert session.scalar(select(func.count()).select_from(TradeExitDeal)) == 1
    (shown,) = _home(session, NOW + timedelta(minutes=1), tmp_path).open_positions
    assert (shown.pnl, shown.close_unconfirmed) == (Decimal("4.50"), False)


def test_equity_unavailable_still_writes_trades_without_snapshot_pnl(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("open_position.json")
    handlers = HistoryServer(data["deals"], [data["position"]]).handlers()
    handlers[p.POSITION_PNL_REQ] = (p.ERROR_RES, {"errorCode": "NEW_CODE", "description": "x"})
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(FakeTransport(handlers)),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
        snapshot_path=snapshot.snapshot_path(tmp_path),
    )
    assert run_ctrader_balance_cycle(factory, config) == []
    assert _trade(session, 5003).status == "open"  # trades written
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code, log.deals_fetched) == (False, "equity_unavailable", 1)
    live = snapshot.read_snapshot(snapshot.snapshot_path(tmp_path))[(account.id, 5003)]
    assert (live.price_current, live.pnl) == (None, None)


def test_equity_unavailable_and_skipped_positions_keep_both_messages(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    entry = load("closed_simple.json")["deals"][0]  # unreported: skipped
    handlers = HistoryServer([entry]).handlers()
    handlers[p.POSITION_PNL_REQ] = (p.ERROR_RES, {"errorCode": "NEW_CODE", "description": "x"})
    config = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(FakeTransport(handlers)),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
    )
    run_ctrader_balance_cycle(factory, config)
    log = _last_log(session, account.id)
    assert (log.ok, log.error_code) == (False, "equity_unavailable")
    message = log.error_message or ""
    assert "equity not read" in message
    assert "positions skipped" in message
    assert "5001" in message

"""cTrader phase c through the worker job: c1 specs, c2 conversion rates, c3 trade risk.

Fixture JSON and the fake server only (`tests/ctrader_phase_c_fakes.py`), no live call. All
numbers are synthetic. MT5 parity: the same domain deals go through the same shared writer for
an MT5 account (`_mt5_twin`) and the risk fields must match the cTrader trade.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import get_rules
from app.ctrader.convert import convert
from app.ctrader.history import (
    CtSymbol,
    HistoryRequest,
    TradingRead,
    parse_deal,
    parse_position,
)
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import Account, FxRate, SymbolSpec, SyncLog, Trade
from app.mt5.types import RawSymbolSpec
from app.services import open_positions_snapshot as snapshot
from app.services.calculator_fx import conversion_for
from app.services.trade_writer import TradeBatch, write_trades
from app.worker.ctrader_job import CtraderJobConfig, run_ctrader_balance_cycle
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REFRESH_TOKEN,
    FakeConnector,
    make_ctrader_account,
    make_mt5_account,
    no_sleep,
)
from tests.ctrader_history_fakes import load
from tests.ctrader_phase_c_fakes import ASK, BID, PhaseCServer, tick_points
from tests.symbols_fixture import TEST_SYMBOLS

D = Decimal
MONDAY = datetime(2026, 11, 23, tzinfo=UTC)
NOW = MONDAY.replace(hour=12)
EIGHT_PLACES = D("0.00000001")  # fx_rates.rate is NUMERIC(20,8)
DAY_MS = 86_400_000


def ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


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
    return make_ctrader_account(session, reference_balance=D("1000.00"))


def run(
    factory: sessionmaker[Session],
    store: TokenStore,
    server: PhaseCServer,
    tmp_path: Path,
    at: datetime = NOW,
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


def specs_of(session: Session, account: Account) -> dict[str, SymbolSpec]:
    session.expire_all()
    rows = session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account.id))
    return {row.symbol: row for row in rows}


def rates_of(session: Session, account: Account) -> dict[tuple[str, str], FxRate]:
    session.expire_all()
    rows = session.scalars(select(FxRate).where(FxRate.account_id == account.id))
    return {(row.from_currency, row.to_currency): row for row in rows}


def trade_of(session: Session, position_id: int, account: Account) -> Trade:
    session.expire_all()
    return session.scalars(
        select(Trade).where(Trade.position_id == position_id, Trade.account_id == account.id)
    ).one()


def last_log(session: Session, account: Account) -> SyncLog:
    session.expire_all()
    return session.scalars(
        select(SyncLog).where(SyncLog.account_id == account.id).order_by(SyncLog.id.desc())
    ).first()  # type: ignore[return-value]


def eurusd_ticks() -> dict[str, dict[int, list[tuple[int, Decimal]]]]:
    return {"EURUSD": tick_points("EURUSD")}


def trading(name: str) -> tuple[list[Any], list[Any], list[Any]]:
    data = load(name)
    return data["deals"], [data["position"]], [data["pnl"]]


# --- c1: specs are written ------------------------------------------------------------------


def test_config_symbols_get_specs_with_canonical_names(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    assert run(factory, store, PhaseCServer(ticks=eurusd_ticks()), tmp_path) == [account.id]

    rows = specs_of(session, account)
    # symbols.yaml: EURUSD, GBPUSD (not at this broker), XAUUSD, GER40 = DE40 here. OLDCFD is
    # archived (no full spec) and US100 is neither configured nor traded: no rows.
    assert set(rows) == {"EURUSD", "DE40", "XAUUSD"}
    eurusd, de40, gold = rows["EURUSD"], rows["DE40"], rows["XAUUSD"]
    assert (eurusd.canonical_symbol, de40.canonical_symbol) == ("EURUSD", "GER40")
    assert (eurusd.contract_size, eurusd.tick_size, eurusd.point) == (
        D("100000"),
        D("0.00001"),
        D("0.00001"),
    )
    assert (eurusd.tick_value, eurusd.tick_value_loss, eurusd.digits) == (D("1"), D("1"), 5)
    assert (eurusd.volume_min, eurusd.volume_step, eurusd.volume_max) == (
        D("0.01"),
        D("0.01"),
        D("1000"),
    )
    assert (eurusd.currency_profit, eurusd.currency_margin) == ("USD", "EUR")
    assert (de40.contract_size, de40.tick_size, de40.digits) == (D("1"), D("0.1"), 1)
    assert (de40.volume_min, de40.volume_step, de40.volume_max) == (D("0.1"), D("0.1"), D("1000"))
    assert (de40.currency_profit, de40.tick_value_loss) == ("EUR", D("0.1"))
    assert (gold.contract_size, gold.tick_size, gold.volume_max) == (D("100"), D("0.01"), D("100"))
    assert all(row.mt5_loss_per_tick is None for row in rows.values())  # no order_calc_profit
    assert all(row.synced_at == NOW for row in rows.values())


def test_trade_symbol_outside_the_config_gets_a_spec_and_its_risk(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    deals, positions, pnl = trading("open_us100.json")
    run(factory, store, PhaseCServer(deals, positions, pnl), tmp_path)

    us100 = specs_of(session, account)["US100"]
    assert (us100.canonical_symbol, us100.contract_size, us100.tick_size) == (
        "US100",
        D("1"),
        D("0.01"),
    )
    trade = trade_of(session, 5202, account)
    # buy 1 lot, entry 21000.00, SL 20980.00 = 2000 ticks x 0.01 x 1 lot
    assert (trade.risk_amount, trade.r_multiple, trade.status) == (D("20.00"), None, "open")


def test_specs_refresh_at_most_once_per_hour(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = PhaseCServer(ticks=eurusd_ticks())
    run(factory, store, server, tmp_path, NOW)
    asked = server.count(2116)
    assert asked >= 1

    run(factory, store, server, tmp_path, NOW + timedelta(minutes=30))
    assert {r.synced_at for r in specs_of(session, account).values()} == {NOW}
    assert server.count(2116) == asked  # nothing re-read inside the hour

    later = NOW + timedelta(minutes=61)
    run(factory, store, server, tmp_path, later)
    assert {r.synced_at for r in specs_of(session, account).values()} == {later}
    assert server.count(2116) > asked


def test_a_symbol_with_a_bad_field_is_skipped_not_written_half(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = PhaseCServer(ticks=eurusd_ticks())
    server.symbols = copy.deepcopy(server.symbols)
    for item in server.symbols["byId"]["symbol"]:
        if item["symbolId"] == 41:
            item["lotSize"] = 0
    with caplog.at_level(logging.WARNING):
        assert run(factory, store, server, tmp_path) == [account.id]
    assert set(specs_of(session, account)) == {"EURUSD", "DE40"}
    assert any("XAUUSD" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


def test_mt5_accounts_and_their_specs_are_untouched(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    mt5 = make_mt5_account(session)
    long_ago = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    session.add(
        SymbolSpec(
            account_id=mt5.id,
            symbol="EURUSD",
            canonical_symbol="EURUSD",
            contract_size=D("100000"),
            tick_size=D("0.00001"),
            tick_value=D("1"),
            point=D("0.00001"),
            tick_value_loss=D("1"),
            volume_min=D("0.01"),
            volume_step=D("0.01"),
            volume_max=D("100"),
            digits=5,
            currency_profit="USD",
            currency_margin="USD",
            synced_at=long_ago,
        )
    )
    session.commit()

    run(factory, store, PhaseCServer(ticks=eurusd_ticks()), tmp_path)

    mt5_rows = specs_of(session, mt5)
    assert set(mt5_rows) == {"EURUSD"}
    assert (mt5_rows["EURUSD"].synced_at, mt5_rows["EURUSD"].volume_max) == (long_ago, D("100"))
    assert rates_of(session, mt5) == {}


# --- c2: conversion rate ----------------------------------------------------------------------


def test_direct_pair_uses_the_last_ask_and_loss_per_tick_follows(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = PhaseCServer(ticks=eurusd_ticks())
    run(factory, store, server, tmp_path)

    row = rates_of(session, account)[("EUR", "USD")]  # DE40 profits in EUR, account in USD
    assert (row.pair, row.inverted) == ("EURUSD", False)
    # delta-encoded ticks decode to: last BID 1.08034 (11:50), last ASK 1.08044 (11:55)
    assert (row.bid, row.ask, row.rate) == (D("1.08034"), D("1.08044"), D("1.08044"))
    assert row.rate_at == NOW.replace(hour=11, minute=55)
    assert row.synced_at == NOW
    asked = {(sid, kind) for sid, kind, _lo, _hi in server.tick_requests}
    assert {(1, BID), (1, ASK)} <= asked  # EURUSD, both sides
    for _sid, _kind, lo, hi in server.tick_requests:
        assert ms(NOW) - 3_700_000 <= lo <= hi <= ms(NOW) + 60_000  # the last 60 min (+ pad)

    de40 = specs_of(session, account)["DE40"]
    conversion = conversion_for(session, account.id, de40, "USD", NOW)
    assert conversion.source == "rate"  # mt5_loss_per_tick is NULL for cTrader
    assert conversion.rate_loss_per_tick == D("0.1") * D("1") * D("1.08044")


def test_inverse_pair_uses_one_over_the_last_bid(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    tmp_path: Path,
) -> None:
    eur_account = make_ctrader_account(session, currency="EUR", reference_balance=D("1000.00"))
    run(factory, store, PhaseCServer(ticks=eurusd_ticks()), tmp_path)

    row = rates_of(session, eur_account)[("USD", "EUR")]  # XAUUSD profits in USD
    assert (row.pair, row.inverted) == ("EURUSD", True)
    assert (row.bid, row.ask) == (D("1.08034"), D("1.08044"))
    assert row.rate == (D(1) / D("1.08034")).quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
    gold = specs_of(session, eur_account)["XAUUSD"]
    conversion = conversion_for(session, eur_account.id, gold, "EUR", NOW)
    assert (conversion.inverted, conversion.side, conversion.source) == (True, "bid", "rate")
    assert conversion.rate_loss_per_tick == D("0.01") * D("100") * row.rate


def test_no_tick_in_the_last_hour_falls_back_to_three_days(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = PhaseCServer(ticks={"EURUSD": tick_points("EURUSD_weekend")})
    assert run(factory, store, server, tmp_path) == [account.id]

    row = rates_of(session, account)[("EUR", "USD")]
    assert (row.bid, row.ask, row.rate) == (D("1.07990"), D("1.08000"), D("1.08000"))
    assert row.rate_at == datetime(2026, 11, 20, 21, 0, 1, tzinfo=UTC)
    widths = [hi - lo for _sid, _kind, lo, hi in server.tick_requests]
    assert any(width < 4_000_000 for width in widths)  # the 60 min window came first
    assert any(3 * DAY_MS <= width <= 3 * DAY_MS + 3_600_000 for width in widths)  # then 3 days


def test_no_tick_at_all_warns_and_keeps_the_old_rate_row(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_at = NOW - timedelta(days=5)
    session.add(
        FxRate(
            account_id=account.id,
            from_currency="EUR",
            to_currency="USD",
            pair="EURUSD",
            inverted=False,
            bid=D("1.04990"),
            ask=D("1.05000"),
            rate=D("1.05000"),
            rate_at=old_at,
            synced_at=old_at,
        )
    )
    session.commit()

    with caplog.at_level(logging.WARNING):
        assert run(factory, store, PhaseCServer(), tmp_path) == [account.id]  # sync still ok

    row = rates_of(session, account)[("EUR", "USD")]
    assert (row.rate, row.bid, row.ask, row.rate_at, row.synced_at) == (
        D("1.05000"),
        D("1.04990"),
        D("1.05000"),
        old_at,
        old_at,
    )
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("EURUSD" in message for message in warned)
    assert last_log(session, account).ok is True


def test_a_failed_tick_request_never_fails_the_balance_and_stores_no_rate(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    server = PhaseCServer(ticks=eurusd_ticks())
    handlers = server.handlers

    def broken() -> Any:
        patched = handlers()
        patched[2145] = (2142, {"errorCode": "INVALID_REQUEST", "description": "synthetic"})
        return patched

    server.handlers = broken  # type: ignore[method-assign]
    run(factory, store, server, tmp_path)

    session.expire_all()
    stored = session.get(Account, account.id)
    assert stored is not None
    assert stored.balance == D("1000.50")
    assert rates_of(session, account) == {}


# --- c3: trade risk from the initial SL, like MT5 -----------------------------------------------

EURUSD_MT5 = RawSymbolSpec(  # what MT5 reports for the same instrument
    name="EURUSD",
    digits=5,
    contract_size=D("100000"),
    tick_size=D("0.00001"),
    tick_value=D("1"),
    volume_min=D("0.01"),
    volume_step=D("0.01"),
    volume_max=D("100"),
    currency_profit="USD",
    currency_margin="EUR",
    point=D("0.00001"),
    tick_value_loss=D("1"),
)
DE40_MT5 = RawSymbolSpec(
    name="DE40",
    digits=1,
    contract_size=D("1"),
    tick_size=D("0.1"),
    tick_value=D("0.1"),
    volume_min=D("0.1"),
    volume_step=D("0.1"),
    volume_max=D("1000"),
    currency_profit="EUR",
    currency_margin="EUR",
    point=D("0.1"),
    tick_value_loss=D("0.1"),
)
CT_SYMBOLS = {1: CtSymbol(1, "EURUSD", 5, 10000000), 2: CtSymbol(2, "DE40", 1, 100)}


def _mt5_twin(
    session: Session,
    steps: Sequence[tuple[list[Any], list[Any]]],
    spec: RawSymbolSpec,
    fx_loss: Decimal | None,
    position_id: int,
) -> Trade:
    """The same deals/positions through the shared writer for an MT5 account, step by step."""
    mt5 = make_mt5_account(session, reference_balance=D("1000.00"), currency="USD")
    for raw_deals, raw_positions in steps:
        deals = tuple(d for d in map(parse_deal, raw_deals) if d is not None)
        positions = tuple(p for p in map(parse_position, raw_positions) if p is not None)
        request = HistoryRequest(MONDAY, NOW)
        read = TradingRead(request, MONDAY, NOW, deals, positions, CT_SYMBOLS)
        converted = convert(read)
        batch = TradeBatch(
            deals=converted.deals,
            position_ids=converted.position_ids,
            snapshots=converted.snapshots,
            balance=D("1000.00"),
            currency="USD",
            specs={spec.name: spec},
            fx_loss={spec.name: fx_loss},
        )
        write_trades(session, mt5, batch, get_rules(), TEST_SYMBOLS)
        session.commit()
    return trade_of(session, position_id, mt5)


def _risk_fields(trade: Trade) -> tuple[Any, ...]:
    return (trade.risk_amount, trade.risk_pct, trade.r_multiple, trade.initial_sl, trade.status)


def test_open_same_currency_trade_has_risk_from_the_sl_and_the_spec_but_no_r(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    deals, positions, pnl = trading("open_position.json")  # EURUSD sell 0.20, SL 1.09
    run(factory, store, PhaseCServer(deals, positions, pnl), tmp_path)

    trade = trade_of(session, 5003, account)
    # entry 1.0865, SL 1.09 = 350 ticks x 1.00 USD x 0.20 lot
    assert (trade.risk_amount, trade.r_multiple, trade.status) == (D("70.00"), None, "open")
    assert trade.risk_pct == D("7")  # of reference_balance 1000
    twin = _mt5_twin(session, [(deals, positions)], EURUSD_MT5, None, 5003)
    assert _risk_fields(trade) == _risk_fields(twin)


def test_open_cross_currency_trade_risk_uses_the_fx_loss_per_tick(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    deals, positions, pnl = trading("open_de40.json")  # DE40 buy 1 lot, 19500.0, SL 19480.0
    run(factory, store, PhaseCServer(deals, positions, pnl, ticks=eurusd_ticks()), tmp_path)

    trade = trade_of(session, 5201, account)
    loss_per_tick = D("0.1") * D("1") * D("1.08044")  # tick_size * contract_size * EURUSD ask
    assert trade.risk_amount == D("21.61")  # 200 ticks x 0.108044 x 1 lot
    assert trade.r_multiple is None
    twin = _mt5_twin(session, [(deals, positions)], DE40_MT5, loss_per_tick, 5201)
    assert _risk_fields(trade) == _risk_fields(twin)


def test_cross_currency_trade_without_any_rate_has_no_risk_but_syncs(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    deals, positions, pnl = trading("open_de40.json")
    assert run(factory, store, PhaseCServer(deals, positions, pnl), tmp_path) == [account.id]

    trade = trade_of(session, 5201, account)
    assert (trade.risk_amount, trade.risk_pct, trade.status) == (None, None, "open")
    assert last_log(session, account).ok is True


def test_breakeven_close_keeps_the_risk_from_the_sl_and_gets_r(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    data = load("closed_simple.json")  # EURUSD buy 0.10, SL 1.08412 (100 ticks below entry)
    entry, exit_ = copy.deepcopy(data["deals"])
    exit_["executionPrice"] = entry["executionPrice"]  # closed at the entry price
    exit_["closePositionDetail"]["entryPrice"] = entry["executionPrice"]
    exit_["closePositionDetail"]["grossProfit"] = 0
    position = data["open_position"]
    pnl = [data["open_pnl"]]

    run(factory, store, PhaseCServer([entry], [position], pnl), tmp_path, NOW.replace(hour=10))
    assert trade_of(session, 5001, account).risk_amount == D("10.00")  # 100 ticks x 1.00 x 0.10
    run(factory, store, PhaseCServer([entry, exit_]), tmp_path, NOW.replace(hour=10, minute=40))

    trade = trade_of(session, 5001, account)
    assert (trade.status, trade.gross_pnl) == ("needs_description", D("0.00"))
    assert (trade.risk_amount, trade.net_pnl) == (D("10.00"), D("-0.70"))
    assert trade.r_multiple == D("-0.07")
    twin = _mt5_twin(session, [([entry], [position]), ([entry, exit_], [])], EURUSD_MT5, None, 5001)
    assert _risk_fields(trade) == _risk_fields(twin)

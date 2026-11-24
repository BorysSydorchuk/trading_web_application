"""cTrader history (phase b): parsing, one-week windows, hasMore paging, conversion to deals.

Recorded-shape JSON fixtures only (tests/fixtures/ctrader/), no live call.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.convert import convert, lots
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import (
    MAX_READ_SPAN,
    RANGE_PAD,
    CtPosition,
    CtSymbol,
    HistoryRequest,
    TradingRead,
    ms_from_utc,
    parse_deal,
    parse_position,
    read_deals,
    read_range,
    read_symbols,
    read_trading,
    utc_from_ms,
)
from app.ctrader.reader import BalanceRead, Credentials, read_balances
from app.domain.trade_builder import DealEntry, DealType, build_trades
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    CTID,
    FakeConnector,
    FakeTransport,
    no_sleep,
)
from tests.ctrader_history_fakes import HistoryServer, load

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
EURUSD = CtSymbol(1, "EURUSD", 5, 10_000_000)


def _run[T](transport: FakeTransport, body: Callable[[CtraderConnection], Awaitable[T]]) -> T:
    async def scenario() -> T:
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=no_sleep)
        await connection.start()
        try:
            return await body(connection)
        finally:
            await connection.close()

    return asyncio.run(scenario())


def _code(caught: pytest.ExceptionInfo[CtraderError]) -> CtraderErrorCode:
    return caught.value.code


# --- parsing -----------------------------------------------------------------------------


def test_deal_with_names_and_close_detail_is_parsed_exactly() -> None:
    raw = load("closed_simple.json")["deals"][1]
    deal = parse_deal(raw)
    assert deal is not None
    assert (deal.deal_id, deal.order_id, deal.position_id, deal.symbol_id) == (9002, 8002, 5001, 1)
    assert deal.side == "sell"
    assert deal.volume == 1_000_000
    assert deal.price == Decimal("1.08712")
    assert deal.time == datetime(2026, 11, 23, 10, 30, tzinfo=UTC)
    assert deal.close is not None
    assert deal.close.gross_profit == Decimal("20.00")
    assert deal.close.commission == Decimal("-0.70")
    assert deal.close.swap == Decimal("0.00")
    assert deal.close.fee == Decimal(0)
    assert deal.close.closed_volume == 1_000_000


def test_deal_with_numeric_enums_and_fee() -> None:
    raw = load("commission_swap.json")["deals"][1]
    deal = parse_deal(raw)
    assert deal is not None
    assert deal.close is not None
    assert deal.side == "sell"
    assert (deal.close.swap, deal.close.commission, deal.close.fee) == (
        Decimal("-12.34"),
        Decimal("-3.50"),
        Decimal("-0.10"),
    )


def test_rejected_or_unfilled_deal_is_ignored() -> None:
    rejected = load("commission_swap.json")["deals"][2]
    assert parse_deal(rejected) is None
    unfilled = dict(load("closed_simple.json")["deals"][0], filledVolume=0)
    assert parse_deal(unfilled) is None


def test_int64_as_string_is_accepted() -> None:
    original = load("closed_simple.json")["deals"][0]
    at = original["executionTimestamp"]
    raw = dict(original, dealId="9001", executionTimestamp=str(at))
    deal = parse_deal(raw)
    assert deal is not None
    assert deal.deal_id == 9001
    assert deal.time == utc_from_ms(at, "t") == datetime(2026, 11, 23, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [("executionPrice", None), ("executionPrice", "NaN"), ("tradeSide", 7), ("positionId", 1.5)],
)
def test_malformed_deal_is_a_bad_response(field: str, value: object) -> None:
    raw = dict(load("closed_simple.json")["deals"][0], **{field: value})
    with pytest.raises(CtraderError) as caught:
        parse_deal(raw)
    assert _code(caught) is CtraderErrorCode.BAD_RESPONSE


def test_close_detail_without_money_digits_uses_the_deal_digits() -> None:
    raw = copy.deepcopy(load("closed_simple.json")["deals"][1])
    del raw["closePositionDetail"]["moneyDigits"]
    raw["moneyDigits"] = 3
    deal = parse_deal(raw)
    assert deal is not None
    assert deal.close is not None
    assert deal.close.gross_profit == Decimal("2.000")


def test_open_position_is_parsed_and_a_zero_stop_is_none() -> None:
    raw = load("open_position.json")["position"]
    position = parse_position(raw)
    assert position == CtPosition(
        position_id=5003,
        symbol_id=1,
        side="sell",
        volume=2_000_000,
        open_time=datetime(2026, 11, 23, 11, 0, tzinfo=UTC),
        sl=Decimal("1.09"),
        tp=Decimal("1.08"),
    )
    no_stop = dict(raw, stopLoss=0)
    del no_stop["takeProfit"]
    parsed = parse_position(no_stop)
    assert parsed is not None
    assert (parsed.sl, parsed.tp) == (None, None)


def test_not_open_position_is_ignored() -> None:
    raw = dict(load("open_position.json")["position"], positionStatus="POSITION_STATUS_CLOSED")
    assert parse_position(raw) is None


# --- requests ----------------------------------------------------------------------------


def test_deal_history_is_read_in_windows_of_at_most_one_week() -> None:
    server = HistoryServer(load("two_windows.json")["deals"])
    lo = ms_from_utc(NOW - timedelta(days=30))
    hi = ms_from_utc(NOW)
    deals = _run(server.transport(), lambda c: read_deals(c, CTID, lo, hi))
    assert [d.deal_id for d in deals] == [9031, 9032]
    windows = server.deal_requests
    assert len(windows) == 5
    assert windows[0][0] == lo
    assert windows[-1][1] == hi
    assert all(b - a < p.MAX_DEAL_WINDOW_MS for a, b in windows)
    assert all(nxt[0] == prev[1] + 1 for prev, nxt in itertools.pairwise(windows))
    entry, exit_ = (ms_from_utc(d.time) for d in deals)
    holder = [i for i, (a, b) in enumerate(windows) for at in (entry, exit_) if a <= at <= b]
    assert len(set(holder)) == 2  # the position spans two windows


def test_has_more_splits_the_window_until_every_deal_is_read() -> None:
    server = HistoryServer(load("partial_close.json")["deals"], max_rows=1)
    lo = ms_from_utc(NOW - timedelta(days=1))
    hi = ms_from_utc(NOW)
    deals = _run(server.transport(), lambda c: read_deals(c, CTID, lo, hi))
    assert [d.deal_id for d in deals] == [9011, 9012, 9013]
    assert len(server.deal_requests) > 3


def test_has_more_in_a_single_millisecond_is_a_bad_response() -> None:
    first = load("partial_close.json")["deals"][0]
    twin = dict(first, dealId=9999)
    server = HistoryServer([first, twin], max_rows=1)
    at = int(first["executionTimestamp"])
    with pytest.raises(CtraderError) as caught:
        _run(server.transport(), lambda c: read_deals(c, CTID, at, at))
    assert _code(caught) is CtraderErrorCode.BAD_RESPONSE


def test_deal_list_of_another_account_is_refused() -> None:
    server = HistoryServer()
    handlers = server.handlers()
    handlers[p.DEAL_LIST_REQ] = (
        p.DEAL_LIST_RES,
        {"ctidTraderAccountId": CTID + 1, "deal": [], "hasMore": False},
    )
    with pytest.raises(CtraderError) as caught:
        _run(FakeTransport(handlers), lambda c: read_deals(c, CTID, 0, 10))
    assert _code(caught) is CtraderErrorCode.BAD_RESPONSE


def test_deal_list_uses_the_historical_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    real = CtraderConnection.request

    async def spy(self: CtraderConnection, *args: Any, historical: bool = False) -> Any:
        if args[0] == p.DEAL_LIST_REQ:
            seen.append(historical)
        return await real(self, *args, historical=historical)

    monkeypatch.setattr(CtraderConnection, "request", spy)
    _run(HistoryServer().transport(), lambda c: read_deals(c, CTID, 0, 10))
    assert seen == [True]


def test_symbols_resolve_names_digits_and_lot_size_archived_included() -> None:
    symbols = _run(HistoryServer().transport(), lambda c: read_symbols(c, CTID, {1, 2, 99, 500}))
    assert symbols[1] == EURUSD
    assert symbols[2] == CtSymbol(2, "DE40", 1, 100)
    assert symbols[99] == CtSymbol(99, "OLDCFD", None, None)  # archived: no details
    assert 500 not in symbols


def test_no_symbol_request_without_symbols() -> None:
    transport = HistoryServer().transport()
    assert _run(transport, lambda c: read_symbols(c, CTID, set())) == {}
    assert transport.sent == []


def test_read_range_reaches_back_to_db_open_trades_and_positions() -> None:
    position = parse_position(load("open_position.json")["position"])
    assert position is not None
    old = NOW - timedelta(days=40)
    request = HistoryRequest(NOW - timedelta(days=3), NOW, {7: old})
    start, end = read_range(request, [position], NOW)
    assert start == old - RANGE_PAD
    assert end == NOW + RANGE_PAD
    ancient = HistoryRequest(NOW - timedelta(days=3), NOW, {7: NOW - timedelta(days=900)})
    assert read_range(ancient, [], NOW)[0] == NOW + RANGE_PAD - MAX_READ_SPAN


def test_read_trading_reads_positions_first_then_deals_and_symbols() -> None:
    data = load("open_position.json")
    server = HistoryServer(data["deals"], [data["position"]])
    transport = server.transport()
    request = HistoryRequest(NOW - timedelta(days=1), NOW)
    read = _run(transport, lambda c: read_trading(c, CTID, request, NOW))
    assert transport.types_sent()[0] == p.RECONCILE_REQ
    assert transport.types_sent()[-2:] == [p.SYMBOLS_LIST_REQ, p.SYMBOL_BY_ID_REQ]
    assert [d.deal_id for d in read.deals] == [9041]
    assert [pos.position_id for pos in read.positions] == [5003]
    assert set(read.symbols) == {1}


# --- conversion --------------------------------------------------------------------------


def _read(
    deals: list[dict[str, Any]],
    positions: list[dict[str, Any]] = (),  # type: ignore[assignment]
    open_trades: dict[int, datetime] | None = None,
    symbols: dict[int, CtSymbol] | None = None,
) -> TradingRead:
    parsed = [d for d in (parse_deal(raw) for raw in deals) if d is not None]
    live = [x for x in (parse_position(raw) for raw in positions) if x is not None]
    return TradingRead(
        request=HistoryRequest(NOW - timedelta(days=30), NOW, open_trades or {}),
        read_from=NOW - timedelta(days=30),
        read_to=NOW + RANGE_PAD,
        deals=tuple(parsed),
        positions=tuple(live),
        symbols=symbols
        if symbols is not None
        else {1: EURUSD, 2: CtSymbol(2, "DE40", 1, 100), 41: CtSymbol(41, "XAUUSD", 2, 10_000)},
    )


def test_lots_are_exact_or_unknown() -> None:
    assert lots(1_000_000, EURUSD) == Decimal("0.1")
    assert lots(100, CtSymbol(2, "DE40", 1, 100)) == Decimal(1)
    assert lots(1, CtSymbol(3, "ODD", 2, 3)) is None
    assert lots(100, CtSymbol(3, "NOLOT", 2, None)) is None


def test_simple_close_becomes_entry_and_exit_deals_with_close_money() -> None:
    converted = convert(_read(load("closed_simple.json")["deals"]))
    entry, exit_ = converted.deals
    assert (entry.entry, entry.type, entry.volume) == (DealEntry.IN, DealType.BUY, Decimal("0.1"))
    assert (entry.commission, entry.profit) == (Decimal(0), Decimal(0))  # booked with the close
    assert (exit_.entry, exit_.type, exit_.volume) == (DealEntry.OUT, DealType.SELL, Decimal("0.1"))
    assert (exit_.profit, exit_.commission, exit_.swap) == (
        Decimal("20.00"),
        Decimal("-0.70"),
        Decimal("0.00"),
    )
    assert exit_.symbol == "EURUSD"
    assert converted.position_ids == {5001}
    built = build_trades(converted.deals).trades[0]
    assert built.net_pnl == Decimal("19.30")
    assert built.is_closed


def test_partial_close_builds_one_trade_with_two_exits() -> None:
    converted = convert(_read(load("partial_close.json")["deals"]))
    result = build_trades(converted.deals)
    trade = result.trades[0]
    assert (trade.volume, trade.exit_volume, trade.open_volume) == (Decimal(2), Decimal(2), Decimal(0))
    assert len(trade.exit_deals) == 2
    assert trade.exit_price == Decimal("19485.50000000")
    assert (trade.gross_pnl, trade.commission, trade.net_pnl) == (
        Decimal("30.00"),
        Decimal("-1.00"),
        Decimal("29.00"),
    )


def test_commission_swap_and_conversion_fee() -> None:
    converted = convert(_read(load("commission_swap.json")["deals"]))
    trade = build_trades(converted.deals).trades[0]
    assert trade.volume == Decimal("0.5")
    assert (trade.gross_pnl, trade.swap, trade.commission) == (
        Decimal("275.00"),
        Decimal("-12.34"),
        Decimal("-3.60"),
    )
    assert trade.net_pnl == Decimal("259.06")
    assert converted.position_ids == {5004}  # the rejected deal's position is not built


def test_unknown_lot_size_or_symbol_skips_the_position_visibly() -> None:
    deals = load("closed_simple.json")["deals"]
    no_lot = convert(_read(deals, symbols={1: CtSymbol(1, "EURUSD", 5, None)}))
    assert no_lot.position_ids == set()
    assert [s.position_id for s in no_lot.skipped] == [5001]
    assert "lot size" in no_lot.skipped[0].reason
    unknown = convert(_read(deals, symbols={}))
    assert "unknown" in unknown.skipped[0].reason


def test_exit_only_position_before_the_range_is_ignored_unless_db_open() -> None:
    exit_only = [load("closed_simple.json")["deals"][1]]
    ignored = convert(_read(exit_only))
    assert (ignored.before_range, ignored.skipped, ignored.deals) == ([5001], [], [])
    tracked = convert(_read(exit_only, open_trades={5001: NOW - timedelta(days=400)}))
    assert [s.position_id for s in tracked.skipped] == [5001]


def test_db_open_trade_without_its_entry_deal_is_a_missing_entry() -> None:
    converted = convert(_read([], open_trades={5001: datetime(2026, 11, 23, 9, tzinfo=UTC)}))
    assert converted.missing_entries == [5001]
    assert converted.unconfirmed == [5001]


def test_reported_position_without_its_entry_deal_is_a_missing_entry() -> None:
    data = load("open_position.json")
    assert convert(_read([], [data["position"]])).missing_entries == [5003]
    assert convert(_read(data["deals"], [data["position"]])).missing_entries == []


def test_open_position_snapshot_has_stops_and_lots() -> None:
    data = load("open_position.json")
    converted = convert(_read(data["deals"], [data["position"]]))
    snapshot = converted.snapshots[5003]
    assert (snapshot.sl, snapshot.tp, snapshot.volume) == (
        Decimal("1.09000"),
        Decimal("1.08000"),
        Decimal("0.2"),
    )


def test_db_open_trade_closed_in_the_history_is_not_unconfirmed() -> None:
    deals = load("closed_simple.json")["deals"]
    converted = convert(_read(deals, open_trades={5001: datetime(2026, 11, 23, 9, tzinfo=UTC)}))
    assert converted.unconfirmed == []
    assert converted.missing_entries == []


# --- reader integration ----------------------------------------------------------------


def _balances(transport: FakeTransport, request: HistoryRequest) -> Any:
    async def connector(_url: str) -> FakeTransport:
        return transport

    creds = Credentials(CLIENT_ID, SecretStr(CLIENT_SECRET), SecretStr(ACCESS_TOKEN))
    return asyncio.run(
        read_balances(
            creds,
            [(CTID, False)],
            connector,
            sleep=no_sleep,
            history={CTID: request},
            clock=lambda: NOW,
        )
    )


def test_history_read_is_retried_once_after_a_dropped_connection() -> None:
    server = HistoryServer(load("closed_simple.json")["deals"])
    handlers = server.handlers()
    calls: list[int] = []

    def flaky(frame: dict[str, Any]) -> Any:
        calls.append(1)
        if len(calls) == 1:
            return p.ERROR_RES, {"errorCode": "CH_SERVER_NOT_REACHABLE", "description": "x"}
        return server._deal_list(frame)

    handlers[p.DEAL_LIST_REQ] = flaky
    result = _balances(FakeTransport(handlers), HistoryRequest(NOW - timedelta(days=1), NOW))
    read = result[CTID]
    assert isinstance(read, BalanceRead)
    assert isinstance(read.trading, TradingRead)
    assert [d.deal_id for d in read.trading.deals] == [9001, 9002]
    assert read.balance == Decimal("1000.50")


def test_history_error_is_returned_beside_the_balance() -> None:
    handlers = HistoryServer().handlers()
    handlers[p.RECONCILE_REQ] = (p.ERROR_RES, {"errorCode": "NEW_CODE", "description": "x"})
    read = _balances(FakeTransport(handlers), HistoryRequest(NOW - timedelta(days=1), NOW))[CTID]
    assert isinstance(read, BalanceRead)
    assert isinstance(read.trading, CtraderError)
    assert read.trading.code is CtraderErrorCode.BAD_RESPONSE
    assert read.balance == Decimal("1000.50")


def test_position_pnl_is_kept_by_position_id() -> None:
    data = load("open_position.json")
    server = HistoryServer(data["deals"], [data["position"]], [data["pnl"]])
    read = _balances(server.transport(), HistoryRequest(NOW - timedelta(days=1), NOW))[CTID]
    assert read.position_pnl == {5003: Decimal("-15.34")}
    assert read.equity == Decimal("985.16")


def test_no_history_request_means_no_history_message() -> None:
    transport = FakeTransport(HistoryServer().handlers())

    async def connector(_url: str) -> FakeTransport:
        return transport

    creds = Credentials(CLIENT_ID, SecretStr(CLIENT_SECRET), SecretStr(ACCESS_TOKEN))
    result = asyncio.run(read_balances(creds, [(CTID, False)], connector, sleep=no_sleep))
    assert result[CTID].trading is None  # type: ignore[union-attr]
    assert not {p.RECONCILE_REQ, p.DEAL_LIST_REQ} & set(transport.types_sent())

"""cTrader order history (2183): parsing, paging and the initial-SL rule. No network."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import (
    CloseDetail,
    CtDeal,
    CtPosition,
    CtSymbol,
    HistoryRequest,
    TradingRead,
    ms_from_utc,
)
from app.ctrader.orders import (
    MAX_ORDER_READS,
    MAX_REQUESTS,
    CtOrder,
    InitialStop,
    initial_stop,
    last_protective_stop,
    parse_order,
    read_opening_stops,
    read_position_orders,
    unseen_closed,
)
from tests.ctrader_fakes import CTID, FakeConnector, FakeTransport

T0 = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)


def _order(
    order_id: int,
    *,
    kind: str = "market",
    created: datetime | None = T0,
    filled: bool = True,
    closing: bool = False,
    execution: str | None = "1.10000",
    stop_loss: str | None = None,
    relative: int | None = None,
    stop_price: str | None = None,
) -> CtOrder:
    return CtOrder(
        order_id=order_id,
        position_id=1,
        kind=kind,
        filled=filled,
        closing=closing,
        created=created,
        execution_price=Decimal(execution) if execution is not None else None,
        stop_loss=Decimal(stop_loss) if stop_loss is not None else None,
        relative_stop_loss=relative,
        stop_price=Decimal(stop_price) if stop_price is not None else None,
    )


def _stop(orders: list[CtOrder], side: str = "buy", **kw: Any) -> InitialStop | None:
    entry = kw.pop("entry", Decimal("1.10000"))
    return initial_stop(orders, side=side, entry_price=entry, digits=kw.pop("digits", 5), **kw)


# --- parse ---------------------------------------------------------------------------------


def test_parse_order_reads_names_and_numbers() -> None:
    raw = {
        "orderId": 77,
        "positionId": 5,
        "orderType": "STOP_LOSS_TAKE_PROFIT",
        "orderStatus": "ORDER_STATUS_ACCEPTED",
        "tradeData": {"symbolId": 1, "volume": 100, "tradeSide": 2, "openTimestamp": 1000},
        "stopLoss": 1.2345,
        "relativeStopLoss": 0,
        "closingOrder": False,
    }
    order = parse_order(raw)
    assert (order.order_id, order.position_id, order.kind) == (77, 5, "protective")
    assert (order.filled, order.closing) == (False, False)
    assert order.stop_loss == Decimal("1.2345")
    assert order.relative_stop_loss is None  # 0 = not set
    assert order.created == datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=1)


def test_parse_order_market_filled_by_number() -> None:
    raw = {"orderId": 1, "orderType": 1, "orderStatus": 2, "tradeData": {"tradeSide": 1}}
    order = parse_order(raw)
    assert (order.kind, order.filled, order.created) == ("market", True, None)


def test_parse_order_executed_volume_counts_as_filled() -> None:
    order = parse_order({"orderId": 1, "orderStatus": 5, "executedVolume": 100, "tradeData": {}})
    assert order.filled is True


@pytest.mark.parametrize("bad", [None, [], "x", {"orderId": "a"}])
def test_parse_order_refuses_bad_data(bad: object) -> None:
    with pytest.raises(CtraderError) as caught:
        parse_order(bad)
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


# --- the rule --------------------------------------------------------------------------------


def test_opening_order_absolute_stop() -> None:
    assert _stop([_order(1, stop_loss="1.09500")]) == InitialStop(Decimal("1.09500"), "opening", 1)


def test_relative_stop_buy_is_below_the_execution_price() -> None:
    # 500 / 100 000 = 0.005 -> 1.10000 - 0.00500
    stop = _stop([_order(1, relative=500)])
    assert stop == InitialStop(Decimal("1.09500"), "opening", 1)


def test_relative_stop_sell_is_above_the_execution_price() -> None:
    order = _order(1, execution="25234.0", relative=12_440_000)
    stop = _stop([order], side="sell", entry=Decimal("25234.0"), digits=1)
    assert stop == InitialStop(Decimal("25358.4"), "opening", 1)


def test_relative_stop_without_execution_price_uses_the_entry() -> None:
    stop = _stop([_order(1, execution=None, relative=1000)], entry=Decimal("1.20000"))
    assert stop is not None
    assert stop.sl == Decimal("1.19000")


def test_the_named_opening_order_wins_over_an_earlier_one() -> None:
    orders = [
        _order(1, stop_loss="1.09000"),
        _order(2, created=T0 + timedelta(1), stop_loss="1.09800"),
    ]
    assert _stop(orders, opening_order_id=2) == InitialStop(Decimal("1.09800"), "opening", 2)
    assert _stop(orders) == InitialStop(Decimal("1.09000"), "opening", 1)


def test_closing_and_unfilled_orders_are_never_the_opening_order() -> None:
    orders = [
        _order(1, closing=True, stop_loss="1.09000"),
        _order(2, filled=False, stop_loss="1.09100"),
        _order(3, created=T0 + timedelta(minutes=5), stop_loss="1.09200"),
    ]
    assert _stop(orders) == InitialStop(Decimal("1.09200"), "opening", 3)


def test_protective_order_when_the_opening_order_has_no_stop() -> None:
    orders = [
        _order(1),
        _order(5, kind="protective", created=T0 + timedelta(minutes=3), stop_price="1.09300"),
        _order(4, kind="protective", created=T0 + timedelta(minutes=1), stop_loss="1.09400"),
    ]
    assert _stop(orders) == InitialStop(Decimal("1.09400"), "protective", 4)


@pytest.mark.parametrize("moved", ["1.10000", "1.10200"])
def test_a_stop_at_or_beyond_the_entry_is_never_an_initial_sl(moved: str) -> None:
    orders = [_order(1, stop_loss=moved), _order(2, kind="protective", stop_loss=moved)]
    assert _stop(orders) is None


def test_a_wrong_side_opening_stop_falls_back_to_a_protective_one() -> None:
    orders = [_order(1, stop_loss="1.10500"), _order(2, kind="protective", stop_loss="1.09600")]
    assert _stop(orders) == InitialStop(Decimal("1.09600"), "protective", 2)


def test_sell_side_rule() -> None:
    orders = [_order(1, stop_loss="1.09000")]
    assert _stop(orders, side="sell") is None  # below a sell entry: not a loss stop
    orders = [_order(1, stop_loss="1.10600")]
    assert _stop(orders, side="sell") == InitialStop(Decimal("1.10600"), "opening", 1)


def test_price_is_quantized_to_the_digits() -> None:
    stop = _stop([_order(1, stop_loss="1.0949999999")], digits=5)
    assert stop is not None
    assert stop.sl == Decimal("1.09500")


def test_no_orders_no_stop() -> None:
    assert _stop([]) is None
    assert _stop([_order(1)]) is None


# --- the request ---------------------------------------------------------------------------


def _orders_server(
    orders: list[dict[str, Any]], max_rows: int | None = None, account: int = CTID
) -> tuple[FakeTransport, list[tuple[int, int, int]]]:
    seen: list[tuple[int, int, int]] = []

    def handler(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        payload = frame["payload"]
        pid, lo, hi = (
            int(payload["positionId"]),
            int(payload["fromTimestamp"]),
            int(payload["toTimestamp"]),
        )
        seen.append((pid, lo, hi))
        found = [o for o in orders if lo <= o["utcLastUpdateTimestamp"] <= hi]
        more = max_rows is not None and len(found) > max_rows
        return p.ORDER_LIST_BY_POSITION_RES, {
            "ctidTraderAccountId": account,
            "order": found[:max_rows] if more else found,
            "hasMore": more,
        }

    return FakeTransport({p.ORDER_LIST_BY_POSITION_REQ: handler}), seen


def _raw(order_id: int, at: datetime, position_id: int = 9) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "positionId": position_id,
        "orderType": "MARKET",
        "orderStatus": "ORDER_STATUS_FILLED",
        "utcLastUpdateTimestamp": ms_from_utc(at),
        "tradeData": {"symbolId": 1, "tradeSide": "BUY", "openTimestamp": ms_from_utc(at)},
    }


def _read(transport: FakeTransport, start: datetime, end: datetime) -> tuple[CtOrder, ...]:
    async def scenario() -> tuple[CtOrder, ...]:
        connection = CtraderConnection("wss://fake", FakeConnector(transport))
        await connection.start()
        try:
            return await read_position_orders(connection, CTID, 9, start, end)
        finally:
            await connection.close()

    return asyncio.run(scenario())


def test_read_splits_a_window_with_more_orders() -> None:
    raws = [_raw(i, T0 + timedelta(minutes=i)) for i in range(1, 6)]
    transport, seen = _orders_server(raws, max_rows=2)
    got = _read(transport, T0, T0 + timedelta(hours=1))
    assert [o.order_id for o in got] == [1, 2, 3, 4, 5]
    assert len(seen) > 1
    assert all(pid == 9 for pid, _, _ in seen)


def test_read_uses_windows_of_at_most_one_week() -> None:
    transport, seen = _orders_server([_raw(1, T0 + timedelta(days=9))])
    got = _read(transport, T0, T0 + timedelta(days=10))
    assert [o.order_id for o in got] == [1]
    assert len(seen) == 2
    assert all(hi - lo < p.MAX_DEAL_WINDOW_MS for _, lo, hi in seen)


def test_read_drops_orders_of_another_position() -> None:
    transport, _ = _orders_server([_raw(1, T0, position_id=9), _raw(2, T0, position_id=10)])
    assert [o.order_id for o in _read(transport, T0, T0 + timedelta(minutes=1))] == [1]


def test_read_refuses_an_answer_for_another_account() -> None:
    transport, _ = _orders_server([_raw(1, T0)], account=CTID + 1)
    with pytest.raises(CtraderError) as caught:
        _read(transport, T0, T0 + timedelta(minutes=1))
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


# --- which positions a sync reads --------------------------------------------------------


def _deal(deal_id: int, pid: int, *, close: bool, at: datetime, price: str = "1.10000") -> CtDeal:
    detail = CloseDetail(Decimal(1), Decimal(0), Decimal(0), Decimal(0), 100) if close else None
    return CtDeal(
        deal_id=deal_id,
        order_id=deal_id + 1000,
        position_id=pid,
        symbol_id=1,
        side="sell" if close else "buy",
        volume=100,
        price=Decimal(price),
        time=at,
        close=detail,
    )


def _trading(
    deals: list[CtDeal],
    positions: tuple[CtPosition, ...] = (),
    open_trades: dict[int, datetime] | None = None,
) -> TradingRead:
    request = HistoryRequest(T0, T0 + timedelta(hours=5), open_trades or {})
    symbols = {1: CtSymbol(1, "EURUSD", 5, 100)}
    return TradingRead(request, T0, T0 + timedelta(hours=5), tuple(deals), positions, symbols)


def test_unseen_closed_picks_only_positions_the_app_never_saw_open() -> None:
    t = T0 + timedelta(minutes=10)
    live = CtPosition(3, 1, "buy", 100, t, None, None)
    read = _trading(
        [
            _deal(1, 1, close=False, at=t, price="1.10000"),
            _deal(2, 1, close=False, at=t + timedelta(minutes=1), price="1.10020"),
            _deal(3, 1, close=True, at=t + timedelta(minutes=5)),
            _deal(4, 2, close=True, at=t),  # entry before the read range
            _deal(5, 3, close=False, at=t),  # open now
            _deal(6, 4, close=False, at=t),
            _deal(7, 4, close=True, at=t + timedelta(minutes=2)),  # DB-open: seen open
            _deal(8, 5, close=False, at=t),  # entry only
        ],
        positions=(live,),
        open_trades={4: t},
    )
    found = unseen_closed(read)
    assert [u.position_id for u in found] == [1]
    item = found[0]
    assert (item.side, item.entry_price, item.opening_order_id) == ("buy", Decimal("1.1001"), 1001)
    assert item.start < t
    assert item.end > t + timedelta(minutes=5)


def _stops(transport: FakeTransport, read: TradingRead) -> dict[int, Decimal]:
    async def scenario() -> dict[int, Decimal]:
        connection = CtraderConnection("wss://fake", FakeConnector(transport))
        await connection.start()
        try:
            return (await read_opening_stops(connection, CTID, read)).initial
        finally:
            await connection.close()

    return asyncio.run(scenario())


def _closed_pair(pid: int, at: datetime) -> list[CtDeal]:
    return [
        _deal(pid * 10, pid, close=False, at=at),
        _deal(pid * 10 + 1, pid, close=True, at=at + timedelta(minutes=1)),
    ]


def test_read_opening_stops_maps_position_to_sl() -> None:
    at = T0 + timedelta(minutes=10)
    raw = _raw(1010, at, position_id=1)
    raw["relativeStopLoss"] = 500
    raw["executionPrice"] = 1.1
    transport, _ = _orders_server([raw])
    assert _stops(transport, _trading(_closed_pair(1, at))) == {1: Decimal("1.09500")}


def test_read_opening_stops_is_capped_per_sync() -> None:
    at = T0 + timedelta(minutes=10)
    deals = [d for pid in range(1, MAX_ORDER_READS + 4) for d in _closed_pair(pid, at)]
    transport, seen = _orders_server([])
    assert _stops(transport, _trading(deals)) == {}
    assert len({pid for pid, _, _ in seen}) == MAX_ORDER_READS


def test_a_refused_order_read_skips_the_position_only() -> None:
    def refuse(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return p.ERROR_RES, {"errorCode": "INVALID_REQUEST", "description": "no"}

    at = T0 + timedelta(minutes=10)
    transport = FakeTransport({p.ORDER_LIST_BY_POSITION_REQ: refuse})
    assert _stops(transport, _trading(_closed_pair(1, at))) == {}


@pytest.mark.parametrize("server_code", ["CH_ACCESS_TOKEN_INVALID", "SERVER_IS_UNDER_MAINTENANCE"])
def test_an_access_or_connection_failure_fails_the_read(server_code: str) -> None:
    def refuse(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return p.ERROR_RES, {"errorCode": server_code, "description": "no"}

    at = T0 + timedelta(minutes=10)
    transport = FakeTransport({p.ORDER_LIST_BY_POSITION_REQ: refuse})
    with pytest.raises(CtraderError):
        _stops(transport, _trading(_closed_pair(1, at)))


def test_unseen_closed_skips_positions_stored_with_an_sl() -> None:
    at = T0 + timedelta(minutes=10)
    read = _trading(_closed_pair(1, at) + _closed_pair(2, at))
    request = HistoryRequest(T0, T0 + timedelta(hours=5), {}, frozenset({1}))
    known = TradingRead(request, read.read_from, read.read_to, read.deals, (), read.symbols)
    assert [u.position_id for u in unseen_closed(known)] == [2]


def test_an_absurd_price_skips_the_position_only() -> None:
    at = T0 + timedelta(minutes=10)
    raw = _raw(1010, at, position_id=1)
    raw["stopLoss"] = 1e300  # cannot be quantized to 5 digits
    transport, _ = _orders_server([raw])
    assert _stops(transport, _trading(_closed_pair(1, at))) == {}


def test_a_hasmore_storm_is_bounded() -> None:
    def always_more(frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return p.ORDER_LIST_BY_POSITION_RES, {
            "ctidTraderAccountId": CTID,
            "order": [],
            "hasMore": True,
        }

    transport = FakeTransport({p.ORDER_LIST_BY_POSITION_REQ: always_more})
    with pytest.raises(CtraderError) as caught:
        _read(transport, T0, T0 + timedelta(days=6))
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE
    assert transport.types_sent().count(p.ORDER_LIST_BY_POSITION_REQ) <= MAX_REQUESTS


def test_last_protective_stop_is_the_latest_protective_order() -> None:
    orders = [
        _order(1, stop_loss="1.09500"),
        _order(2, kind="protective", created=T0 + timedelta(minutes=1), stop_price="1.09500"),
        _order(3, kind="protective", created=T0 + timedelta(minutes=9), stop_price="1.09400"),
    ]
    assert last_protective_stop(orders, 5) == Decimal("1.09400")
    assert last_protective_stop([_order(1, stop_loss="1.09500")], 5) is None

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.trade_builder import (
    NETTING_REVERSAL,
    BuiltTrade,
    Deal,
    DealEntry,
    DealType,
    OrderStops,
    PositionSnapshot,
    SkippedPosition,
    build_trades,
    deal_entry_from_mt5,
    deal_reason_from_mt5,
    deal_type_from_mt5,
    next_status,
)
from app.models.enums import Direction, InitialSlSource, TradeStatus

BUY, SELL = DealType.BUY, DealType.SELL
IN, OUT, INOUT, OUT_BY = DealEntry.IN, DealEntry.OUT, DealEntry.INOUT, DealEntry.OUT_BY

D = Decimal


def t(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


def deal(
    ticket: int,
    position_id: int,
    when: datetime,
    type_: DealType,
    entry: DealEntry,
    volume: str,
    price: str,
    profit: str = "0",
    *,
    symbol: str = "XAUUSD",
    order: int | None = None,
    commission: str = "0",
    swap: str = "0",
    fee: str = "0",
    sl: str | None = None,
    tp: str | None = None,
    reason: str | None = "client",
) -> Deal:
    return Deal(
        ticket=ticket,
        order=order if order is not None else ticket,
        position_id=position_id,
        time=when,
        type=type_,
        entry=entry,
        volume=D(volume),
        price=D(price),
        profit=D(profit),
        commission=D(commission),
        swap=D(swap),
        fee=D(fee),
        symbol=symbol,
        reason=reason,
        sl=D(sl) if sl is not None else None,
        tp=D(tp) if tp is not None else None,
    )


def only(deals: list[Deal], **kwargs: object) -> BuiltTrade:
    result = build_trades(deals, **kwargs)  # type: ignore[arg-type]
    assert result.skipped == []
    assert len(result.trades) == 1
    return result.trades[0]


def test_simple_xauusd_winner() -> None:
    trade = only(
        [
            deal(
                11,
                11,
                t(2, 8, 15, 3),
                BUY,
                IN,
                "0.5",
                "2650.12",
                commission="-1.75",
                sl="2645.00",
                tp="2668.00",
            ),
            deal(
                12,
                11,
                t(2, 9, 1, 44),
                SELL,
                OUT,
                "0.5",
                "2661.40",
                "564.00",
                commission="-1.75",
                sl="2645.00",
                tp="2668.00",
                reason="client",
            ),
        ]
    )
    assert trade.direction is Direction.BUY
    assert trade.open_time == t(2, 8, 15, 3)
    assert trade.close_time == t(2, 9, 1, 44)
    assert trade.duration_seconds == 2801
    assert trade.entry_price == D("2650.12")
    assert trade.exit_price == D("2661.40")
    assert trade.volume == D("0.5")
    assert trade.open_volume == 0
    assert trade.commission == D("-3.50")
    assert trade.gross_pnl == D("564.00")
    assert trade.net_pnl == D("560.50")
    assert trade.initial_sl == D("2645.00")
    assert trade.initial_sl_source is InitialSlSource.DEAL
    assert trade.tp == D("2668.00")
    assert len(trade.exit_deals) == 1
    assert trade.exit_deals[0].reason == "client"


def test_partial_close_three_exits() -> None:
    trade = only(
        [
            deal(1, 1, t(3, 13, 5), SELL, IN, "1.0", "2700.00", commission="-7.00", sl="2705.00"),
            deal(2, 1, t(3, 13, 30), BUY, OUT, "0.3", "2690.00", "300.00", commission="-2.10"),
            deal(3, 1, t(3, 13, 50), BUY, OUT, "0.3", "2685.00", "450.00", commission="-2.10"),
            deal(
                4,
                1,
                t(4, 9, 0),
                BUY,
                OUT,
                "0.4",
                "2695.00",
                "200.00",
                commission="-2.80",
                swap="-1.20",
                reason="tp",
            ),
        ]
    )
    assert trade.direction is Direction.SELL
    assert trade.close_time == t(4, 9, 0)
    assert trade.exit_price == D("2690.50000000")
    assert trade.exit_volume == D("1.0")
    assert [e.volume for e in trade.exit_deals] == [D("0.3"), D("0.3"), D("0.4")]
    assert trade.gross_pnl == D("950.00")
    assert trade.commission == D("-14.00")
    assert trade.swap == D("-1.20")
    assert trade.net_pnl == D("934.80")


def test_partial_close_still_open() -> None:
    trade = only(
        [
            deal(1, 1, t(3, 13, 5), SELL, IN, "1.0", "2700.00", sl="2705.00"),
            deal(2, 1, t(3, 13, 30), BUY, OUT, "0.3", "2690.00", "300.00"),
        ],
        positions={1: PositionSnapshot(sl=D("2700.00"), tp=None, volume=D("0.7"))},
    )
    assert trade.close_time is None
    assert trade.duration_seconds is None
    assert trade.open_volume == D("0.7")
    assert trade.exit_volume == D("0.3")
    assert trade.last_sl == D("2700.00")  # moved to entry on the live position
    assert trade.initial_sl == D("2705.00")


def test_scale_in_vwap() -> None:
    trade = only(
        [
            deal(1, 1, t(2, 8, 0), BUY, IN, "0.5", "1.08500", symbol="EURUSD", sl="1.08200"),
            deal(2, 1, t(2, 8, 20), BUY, IN, "0.5", "1.08300", symbol="EURUSD", order=5),
            deal(3, 1, t(2, 10, 0), SELL, OUT, "1.0", "1.08700", "300.00", symbol="EURUSD"),
        ]
    )
    assert trade.volume == D("1.0")
    assert trade.entry_price == D("1.08400000")
    assert trade.open_time == t(2, 8, 0)
    assert trade.gross_pnl == D("300.00")


def test_losing_trade_by_sl() -> None:
    trade = only(
        [
            deal(
                1,
                7,
                t(2, 13, 10),
                SELL,
                IN,
                "0.8",
                "1.27000",
                symbol="GBPUSD",
                commission="-2.80",
                sl="1.27250",
            ),
            deal(
                2,
                7,
                t(2, 13, 40),
                BUY,
                OUT,
                "0.8",
                "1.27250",
                "-200.00",
                symbol="GBPUSD",
                commission="-2.80",
                sl="1.27250",
                reason="sl",
            ),
        ]
    )
    assert trade.net_pnl == D("-205.60")
    assert trade.exit_deals[0].reason == "sl"
    assert trade.last_sl == D("1.27250")


def test_fee_folded_into_commission() -> None:
    trade = only(
        [
            deal(1, 1, t(2, 8), BUY, IN, "1", "100", commission="-1", fee="-0.25"),
            deal(2, 1, t(2, 9), SELL, OUT, "1", "101", "10", commission="-1", fee="-0.25"),
        ]
    )
    assert trade.commission == D("-2.50")
    assert trade.exit_deals[0].commission == D("-1.25")
    assert trade.net_pnl == D("7.50")


def test_initial_sl_source_order() -> None:
    entry = deal(1, 1, t(2, 8), BUY, IN, "1", "100", order=900)
    exit_ = deal(2, 1, t(2, 9), SELL, OUT, "1", "101", "10")
    by_order = only([entry, exit_], opening_orders={900: OrderStops(sl=D("99"), tp=D("103"))})
    assert (by_order.initial_sl, by_order.initial_sl_source) == (D("99"), InitialSlSource.ORDER)
    assert by_order.tp == D("103")

    by_position = only([entry, exit_], first_seen_sl={1: D("98.5")})
    assert by_position.initial_sl_source is InitialSlSource.POSITION
    assert by_position.initial_sl == D("98.5")

    # deal beats order; sl=0 means "not set"
    with_deal = deal(1, 1, t(2, 8), BUY, IN, "1", "100", order=900, sl="99.5")
    zero_order = only([with_deal, exit_], opening_orders={900: OrderStops(sl=D("0"))})
    assert zero_order.initial_sl_source is InitialSlSource.DEAL


def test_missing_sl_needs_sl() -> None:
    trade = only(
        [
            deal(1, 1, t(2, 8), BUY, IN, "1", "100", sl="0"),
            deal(2, 1, t(2, 9), SELL, OUT, "1", "101", "10"),
        ]
    )
    assert trade.initial_sl is None
    assert trade.initial_sl_source is None
    status = next_status(None, is_closed=trade.is_closed, has_initial_sl=False)
    assert status is TradeStatus.NEEDS_SL


def test_non_trade_deals_ignored() -> None:
    deals = [
        deal(1, 0, t(1, 0), DealType.BALANCE, IN, "0", "0", "100000.00"),
        deal(2, 0, t(2, 0), DealType.COMMISSION, IN, "0", "0", "-5.00"),
        deal(3, 0, t(2, 0), DealType.CREDIT, IN, "0", "0", "50.00"),
        deal(4, 4, t(2, 8), BUY, IN, "1", "100"),
        deal(5, 4, t(2, 9), SELL, OUT, "1", "101", "10"),
    ]
    trade = only(deals)
    assert trade.position_id == 4


def test_multiple_positions_sorted_and_hedged_close_by() -> None:
    result = build_trades(
        [
            deal(10, 20, t(2, 9), SELL, IN, "1", "2000"),
            deal(1, 10, t(2, 8), BUY, IN, "1", "2000"),
            deal(30, 10, t(2, 10), SELL, OUT_BY, "1", "2010", "1000"),
            deal(31, 20, t(2, 10), BUY, OUT_BY, "1", "2010", "-1000"),
        ]
    )
    assert [tr.position_id for tr in result.trades] == [10, 20]
    assert all(tr.is_closed for tr in result.trades)
    assert result.trades[1].net_pnl == D("-1000.00")


def test_inout_reversal_is_skipped() -> None:
    result = build_trades(
        [
            deal(100, 100, t(2, 8), BUY, IN, "1.0", "1.08500", symbol="EURUSD"),
            deal(200, 100, t(2, 9), SELL, INOUT, "1.5", "1.08700", "200.00", symbol="EURUSD"),
            deal(300, 100, t(2, 10), BUY, OUT, "0.5", "1.08600", "50.00", symbol="EURUSD"),
            deal(400, 400, t(2, 8), BUY, IN, "1", "100"),
            deal(401, 400, t(2, 9), SELL, OUT, "1", "101", "100"),
        ]
    )
    assert [tr.position_id for tr in result.trades] == [400]
    assert result.skipped == [SkippedPosition(100, NETTING_REVERSAL)]


def test_skipped_positions() -> None:
    result = build_trades(
        [
            deal(1, 1, t(2, 9), SELL, OUT, "1", "101", "10"),  # entry outside the input
            deal(2, 2, t(2, 8), BUY, IN, "1", "100"),
            deal(3, 2, t(2, 9), SELL, OUT, "2", "101", "10"),  # closes more than open
        ]
    )
    assert result.trades == []
    assert [s.position_id for s in result.skipped] == [1, 2]
    assert "without an entry" in result.skipped[0].reason


@pytest.mark.parametrize(
    ("current", "closed", "has_sl", "expected"),
    [
        (None, False, False, TradeStatus.OPEN),
        (None, True, False, TradeStatus.NEEDS_SL),
        (None, True, True, TradeStatus.NEEDS_DESCRIPTION),
        (TradeStatus.OPEN, True, True, TradeStatus.NEEDS_DESCRIPTION),
        ("needs_sl", True, True, TradeStatus.NEEDS_DESCRIPTION),
        (TradeStatus.DRAFT, True, False, TradeStatus.DRAFT),
        ("complete", True, True, TradeStatus.COMPLETE),
    ],
)
def test_next_status(
    current: TradeStatus | str | None, closed: bool, has_sl: bool, expected: TradeStatus
) -> None:
    assert next_status(current, is_closed=closed, has_initial_sl=has_sl) is expected


def test_mt5_code_mapping() -> None:
    assert deal_type_from_mt5(0) is DealType.BUY
    assert deal_type_from_mt5(2) is DealType.BALANCE
    assert deal_type_from_mt5(17) is DealType.TAX
    assert deal_type_from_mt5(99) is DealType.UNKNOWN
    assert deal_entry_from_mt5(3) is DealEntry.OUT_BY
    with pytest.raises(ValueError, match="entry"):
        deal_entry_from_mt5(4)
    assert deal_reason_from_mt5(4) == "sl"
    assert deal_reason_from_mt5(42) == "unknown_42"

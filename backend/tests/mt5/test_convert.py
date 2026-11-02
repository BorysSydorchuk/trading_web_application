"""Raw MT5 records -> domain inputs: UTC conversion, prices at digits, enum mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.broker_time import BrokerTimeRule, FixedOffset
from app.domain.trade_builder import DealEntry, DealType
from app.mt5.convert import (
    order_stops,
    position_snapshots,
    quantize_price,
    server_epoch,
    server_epoch_range,
    to_deal,
    to_deals,
)
from app.mt5.types import (
    RawDeal,
    RawOrder,
    RawPosition,
    from_json_dict,
    to_decimal,
    to_json_dict,
)

NY = BrokerTimeRule.NY_CLOSE


def sv(wall: str) -> int:
    return server_epoch(datetime.fromisoformat(wall))


def raw_deal(wall: str = "2026-10-19 10:30:00", **kw: object) -> RawDeal:
    data: dict[str, object] = {
        "ticket": 1,
        "order": 2,
        "position_id": 2,
        "time": sv(wall),
        "type": 0,
        "entry": 0,
        "volume": "1",
        "price": "1.0850000000000002",
        "profit": "0",
        "symbol": "EURUSD",
    }
    data.update(kw)
    return from_json_dict(RawDeal, data)


def test_to_deal_converts_server_time_to_utc_and_rounds_price() -> None:
    raw = raw_deal(sl="1.08000000001", tp="0", reason=4, commission="-3")
    deal = to_deal(raw, NY, {"EURUSD": 5})
    assert deal.time == datetime(2026, 10, 19, 7, 30, tzinfo=UTC)  # server UTC+3 (US DST)
    assert deal.price == Decimal("1.08500")
    assert deal.sl == Decimal("1.08000")
    assert deal.tp == Decimal("0.00000")
    assert deal.type is DealType.BUY
    assert deal.entry is DealEntry.IN
    assert deal.reason == "sl"
    assert deal.commission == Decimal("-3")


def test_to_deal_without_digits_keeps_price() -> None:
    deal = to_deal(raw_deal(), NY)
    assert deal.price == Decimal("1.0850000000000002")
    assert deal.sl is None


def test_time_msc_gives_millisecond_precision() -> None:
    t = sv("2026-11-02 10:30:00")
    deal = to_deal(raw_deal(time=t, time_msc=t * 1000 + 250), NY)
    assert deal.time == datetime(2026, 11, 2, 8, 30, 0, 250_000, tzinfo=UTC)  # UTC+2 winter


def test_fixed_offset_conversion() -> None:
    deal = to_deal(raw_deal("2026-10-19 10:30:00"), FixedOffset(2))
    assert deal.time == datetime(2026, 10, 19, 8, 30, tzinfo=UTC)


def test_unknown_entry_code_names_the_deal() -> None:
    with pytest.raises(ValueError, match="deal 1"):
        to_deal(raw_deal(entry=9), NY)


def test_to_deals_dedupes_and_sorts() -> None:
    a = raw_deal("2026-10-19 11:00:00", ticket=5)
    b = raw_deal("2026-10-19 10:00:00", ticket=7)
    deals = to_deals([a, b, a], NY)
    assert [d.ticket for d in deals] == [7, 5]


def test_order_and_position_stops() -> None:
    order = from_json_dict(
        RawOrder,
        {
            "ticket": 1,
            "position_id": 1,
            "time_setup": 0,
            "type": 0,
            "state": 4,
            "volume_initial": "1",
            "price_open": "1.1",
            "sl": "1.0999999999",
            "tp": "0",
            "symbol": "EURUSD",
        },
    )
    stops = order_stops(order, {"EURUSD": 5})
    assert stops.sl == Decimal("1.10000")
    assert stops.tp == 0
    pos = from_json_dict(
        RawPosition,
        {
            "ticket": 3,
            "identifier": 1,
            "time": 0,
            "type": 1,
            "volume": "0.8",
            "price_open": "1.163",
            "sl": "1.165",
            "tp": "0",
            "price_current": "1.1625",
            "profit": "40",
            "symbol": "EURUSD",
        },
    )
    snaps = position_snapshots([pos])
    assert set(snaps) == {1}
    assert snaps[1].sl == Decimal("1.165")
    assert snaps[1].volume == Decimal("0.8")


def test_server_epoch_range_is_padded() -> None:
    start, end = server_epoch_range(
        datetime(2026, 10, 19, 0, 0, tzinfo=UTC), datetime(2026, 10, 20, 0, 0, tzinfo=UTC), NY
    )
    assert start == sv("2026-10-19 02:00:00")  # 00:00 UTC = 03:00 server, minus 1 h pad
    assert end == sv("2026-10-20 04:00:00")
    with pytest.raises(ValueError, match="before"):
        server_epoch_range(datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), NY)


def test_quantize_price() -> None:
    assert quantize_price(Decimal("24150.005"), 2) == Decimal("24150.01")
    assert quantize_price(Decimal("1.5"), None) == Decimal("1.5")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.085, "1.085"), (0.1, "0.1"), (100000, "100000"), ("-3.50", "-3.50")],
)
def test_to_decimal(value: object, expected: str) -> None:
    assert to_decimal(value) == Decimal(expected)
    assert str(to_decimal(value)) == expected


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "abc", None, [1]])
def test_to_decimal_rejects(value: object) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - message varies by input
        to_decimal(value)


def test_json_round_trip_and_validation() -> None:
    raw = raw_deal(sl="1.08")
    assert from_json_dict(RawDeal, to_json_dict(raw)) == raw
    data = to_json_dict(raw) | {"_comment": "ignored"}
    assert from_json_dict(RawDeal, data) == raw
    with pytest.raises(ValueError, match="unknown fields"):
        from_json_dict(RawDeal, to_json_dict(raw) | {"oops": 1})
    with pytest.raises(ValueError, match="expected an integer"):
        from_json_dict(RawDeal, to_json_dict(raw) | {"ticket": "1"})
    missing = to_json_dict(raw)
    del missing["price"]
    with pytest.raises(ValueError, match="RawDeal"):
        from_json_dict(RawDeal, missing)

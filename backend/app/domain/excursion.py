"""MAE / MFE of a trade from a price series (M8-16). Pure, Decimal only, no I/O.

A long trade closes on the bid, so it is measured on bid prices; a short closes
on the ask, so it is measured on ask prices. Distances are in price units and
never negative (a trade that never went favourable has MFE 0).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.models.enums import Direction

_R_STEP = Decimal("0.0001")
_POINTS_STEP = Decimal("0.1")
_ZERO = Decimal(0)


@dataclass(frozen=True)
class PriceSample:
    """One price observation (tick: high == low; M1 bar: high/low of the minute)."""

    time: datetime
    bid_high: Decimal
    bid_low: Decimal
    ask_high: Decimal
    ask_low: Decimal


@dataclass(frozen=True)
class Excursion:
    """Maximum favourable / adverse excursion. R and points may be None."""

    mfe_price: Decimal
    mfe_time: datetime
    mfe_distance: Decimal
    mfe_r: Decimal | None
    mae_price: Decimal
    mae_time: datetime
    mae_distance: Decimal
    mae_r: Decimal | None
    mfe_points: Decimal | None
    mae_points: Decimal | None


def tick(time: datetime, bid: Decimal, ask: Decimal) -> PriceSample:
    """A tick sample: high equals low on both sides."""
    return PriceSample(time, bid, bid, ask, ask)


def bar(time: datetime, high: Decimal, low: Decimal, spread_price: Decimal) -> PriceSample:
    """An M1 bar sample: bid = bar high/low, ask = bid + spread (in price units)."""
    return PriceSample(time, high, low, high + spread_price, low + spread_price)


def _quantize(value: Decimal, step: Decimal) -> Decimal:
    return value.quantize(step, rounding=ROUND_HALF_UP)


def _extreme(
    samples: list[PriceSample], values: list[Decimal], *, highest: bool
) -> tuple[Decimal, datetime]:
    """Extreme value and the earliest sample time that reached it."""
    best = max(values) if highest else min(values)
    first = min(s.time for s, v in zip(samples, values, strict=True) if v == best)
    return best, first


def compute_excursion(
    direction: Direction,
    entry_price: Decimal,
    initial_sl: Decimal | None,
    open_time: datetime,
    end_time: datetime,
    samples: Iterable[PriceSample],
    point: Decimal | None,
) -> Excursion | None:
    """MFE/MAE between open_time and end_time (inclusive); None without samples."""
    if open_time.tzinfo is None or end_time.tzinfo is None:
        raise ValueError("open_time and end_time must be timezone-aware")
    if end_time < open_time:
        raise ValueError("end_time must not be before open_time")

    window = [s for s in samples if open_time <= s.time <= end_time]
    if not window:
        return None

    if direction == Direction.BUY:
        fav_price, fav_time = _extreme(window, [s.bid_high for s in window], highest=True)
        adv_price, adv_time = _extreme(window, [s.bid_low for s in window], highest=False)
        fav_move, adv_move = fav_price - entry_price, entry_price - adv_price
    else:
        fav_price, fav_time = _extreme(window, [s.ask_low for s in window], highest=False)
        adv_price, adv_time = _extreme(window, [s.ask_high for s in window], highest=True)
        fav_move, adv_move = entry_price - fav_price, adv_price - entry_price

    mfe_distance = max(_ZERO, fav_move)
    mae_distance = max(_ZERO, adv_move)
    if mfe_distance == 0:
        fav_price, fav_time = entry_price, open_time
    if mae_distance == 0:
        adv_price, adv_time = entry_price, open_time

    risk = abs(entry_price - initial_sl) if initial_sl is not None else _ZERO

    def to_r(distance: Decimal) -> Decimal | None:
        return _quantize(distance / risk, _R_STEP) if risk > 0 else None

    def to_points(distance: Decimal) -> Decimal | None:
        if point is None or point <= 0:
            return None
        return _quantize(distance / point, _POINTS_STEP)

    return Excursion(
        mfe_price=fav_price,
        mfe_time=fav_time,
        mfe_distance=mfe_distance,
        mfe_r=to_r(mfe_distance),
        mae_price=adv_price,
        mae_time=adv_time,
        mae_distance=mae_distance,
        mae_r=to_r(mae_distance),
        mfe_points=to_points(mfe_distance),
        mae_points=to_points(mae_distance),
    )

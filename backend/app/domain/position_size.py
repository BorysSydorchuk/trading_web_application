"""Prospective price-to-stop sizing; fees and slippage are excluded."""

from dataclasses import dataclass, fields
from decimal import Decimal, DecimalException, localcontext
from typing import Literal

MAX_COEFFICIENT_DIGITS = 64
MAX_ABSOLUTE_EXPONENT = 64
MAX_WORKING_PRECISION = 8192


@dataclass(frozen=True)
class SymbolSpec:
    point: Decimal
    tick_size: Decimal
    tick_value_loss: Decimal
    volume_min: Decimal
    volume_step: Decimal
    volume_max: Decimal


@dataclass(frozen=True)
class PositionSizeRequest:
    direction: Literal["buy", "sell"]
    entry: Decimal
    balance: Decimal
    sl_price: Decimal | None = None
    sl_points: Decimal | None = None
    risk_percent: Decimal | None = Decimal("1")
    risk_amount: Decimal | None = None


@dataclass(frozen=True)
class PositionSizeResult:
    volume: Decimal
    risk_budget: Decimal
    actual_risk: Decimal
    actual_risk_percent: Decimal
    sl_price: Decimal
    sl_distance: Decimal
    tp_1_5: Decimal
    tp_2: Decimal
    tp_3: Decimal


def _positive_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a positive finite Decimal")
    representation = value.as_tuple()
    if (
        len(representation.digits) > MAX_COEFFICIENT_DIGITS
        or abs(int(representation.exponent)) > MAX_ABSOLUTE_EXPONENT
    ):
        raise ValueError(f"{name} exceeds the Decimal representation limit")
    if value <= 0:
        raise ValueError(f"{name} must be a positive finite Decimal")
    return value


def _validate(request: PositionSizeRequest, spec: SymbolSpec) -> list[Decimal]:
    values = [_positive_decimal(getattr(spec, field.name), field.name) for field in fields(spec)]
    values.extend(
        (_positive_decimal(request.entry, "entry"), _positive_decimal(request.balance, "balance"))
    )
    for name in ("sl_price", "sl_points", "risk_percent", "risk_amount"):
        value = getattr(request, name)
        if value is not None:
            values.append(_positive_decimal(value, name))
    if request.direction not in ("buy", "sell"):
        raise ValueError("direction must be buy or sell")
    if (request.sl_price is None) == (request.sl_points is None):
        raise ValueError("Specify exactly one of sl_price and sl_points")
    if (request.risk_percent is None) == (request.risk_amount is None):
        raise ValueError("Specify exactly one of risk_percent and risk_amount")
    if spec.volume_min > spec.volume_max:
        raise ValueError("volume_min must not exceed volume_max")
    return values


def _stop(request: PositionSizeRequest, spec: SymbolSpec) -> tuple[Decimal, Decimal]:
    side = Decimal(1) if request.direction == "buy" else Decimal(-1)
    if request.sl_price is not None:
        stop = request.sl_price
    elif request.sl_points is not None:
        stop = request.entry - side * request.sl_points * spec.point
    else:
        raise ValueError("Specify sl_price or sl_points")
    if stop <= 0 or side * (request.entry - stop) <= 0:
        raise ValueError("SL must be positive and on the loss side of entry")
    if request.entry % spec.tick_size or stop % spec.tick_size:
        raise ValueError("entry and SL must be on the tick-size grid")
    return stop, abs(request.entry - stop)


def _target(
    request: PositionSizeRequest, spec: SymbolSpec, distance: Decimal, ratio: Decimal
) -> Decimal:
    # Entry is already on-grid: round the positive reward distance upward.
    reward = distance * ratio
    ticks = reward // spec.tick_size
    if reward % spec.tick_size:
        ticks += 1
    side = Decimal(1) if request.direction == "buy" else Decimal(-1)
    target = request.entry + side * ticks * spec.tick_size
    if target <= 0:
        raise ValueError("TP targets must be positive")
    return target


def _calculate(request: PositionSizeRequest, spec: SymbolSpec) -> PositionSizeResult:
    if spec.volume_min % spec.volume_step or spec.volume_max % spec.volume_step:
        raise ValueError("Volume limits must be on the zero-based step grid")
    stop, distance = _stop(request, spec)
    budget = request.risk_amount
    if budget is None:
        if request.risk_percent is None:
            raise ValueError("Specify risk_percent or risk_amount")
        budget = request.balance * request.risk_percent / 100
    # Both prices are on-grid, so tick count and per-lot loss are exact.
    loss_per_lot = (distance // spec.tick_size) * spec.tick_value_loss
    # Integer division avoids a rounded quotient crossing a volume boundary.
    steps = min(budget // (loss_per_lot * spec.volume_step), spec.volume_max // spec.volume_step)
    volume = steps * spec.volume_step
    if volume < spec.volume_min:
        raise ValueError("Risk budget cannot support the minimum volume")
    actual_risk = volume * loss_per_lot
    return PositionSizeResult(
        volume=volume,
        risk_budget=budget,
        actual_risk=actual_risk,
        actual_risk_percent=actual_risk * 100 / request.balance,
        sl_price=stop,
        sl_distance=distance,
        tp_1_5=_target(request, spec, distance, Decimal("1.5")),
        tp_2=_target(request, spec, distance, Decimal("2")),
        tp_3=_target(request, spec, distance, Decimal("3")),
    )


def calculate_position_size(request: PositionSizeRequest, spec: SymbolSpec) -> PositionSizeResult:
    """Size within 64 coefficient digits and stored exponents from -64 to 64."""
    values = _validate(request, spec)
    # Cover coefficient lengths and exponent spans of every finite input, with
    # headroom for the fixed chain of products, subtractions and integer divisions.
    # This preserves even budgets arbitrarily close to a step boundary and leaves
    # the caller's Decimal context unchanged. Only the reported percentage may
    # require rounding when its decimal expansion does not terminate.
    precision = 32 + 4 * sum(
        len(value.as_tuple().digits) + abs(int(value.as_tuple().exponent)) for value in values
    )
    if precision > MAX_WORKING_PRECISION:
        raise ValueError("Sizing data exceeds the Decimal working precision limit")
    try:
        with localcontext() as context:
            context.prec = max(28, precision)
            return _calculate(request, spec)
    except DecimalException as exc:
        raise ValueError("Sizing data exceeds Decimal arithmetic limits") from exc

"""Prospective price-to-stop sizing; fees and slippage are excluded."""

from dataclasses import dataclass, fields
from decimal import Decimal, DecimalException, localcontext
from typing import Any, Literal

MAX_COEFFICIENT_DIGITS = 64
MAX_ABSOLUTE_EXPONENT = 64
MAX_WORKING_PRECISION = 8192

ErrorCode = Literal[
    "invalid_stop",
    "off_tick_grid",
    "below_min_volume",
    "invalid_targets",
    "specs_invalid",
    "validation_error",
]


class PositionSizeError(ValueError):
    """Rejected sizing input with a stable `code` (docs/api.md M5-04c) for the API mapping.

    `fields` names the offending inputs where meaningful. `min_volume_risk` is the risk at
    the minimum volume, set for `below_min_volume` only (full core precision).
    """

    def __init__(
        self,
        message: str,
        code: ErrorCode,
        field_names: tuple[str, ...] = (),
        *,
        min_volume_risk: Decimal | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.fields = field_names
        self.min_volume_risk = min_volume_risk

    def __reduce__(self) -> tuple[Any, ...]:
        # Rebuild with every constructor argument so pickle and copy round-trip.
        return (
            _rebuild_position_size_error,
            (str(self), self.code, self.fields, self.min_volume_risk),
        )


def _rebuild_position_size_error(
    message: str,
    code: ErrorCode,
    field_names: tuple[str, ...],
    min_volume_risk: Decimal | None,
) -> PositionSizeError:
    return PositionSizeError(message, code, field_names, min_volume_risk=min_volume_risk)


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


def check_positive_decimal(
    value: object,
    name: str,
    code: ErrorCode = "validation_error",
    *,
    names_request_field: bool = True,
) -> Decimal:
    """Positive finite Decimal within the representation limits, else PositionSizeError.

    `names_request_field` puts `name` in the error's `fields` (a request input); pass
    False for spec values, which are not request fields.
    """
    named = (name,) if names_request_field else ()
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PositionSizeError(f"{name} must be a positive finite Decimal", code, named)
    representation = value.as_tuple()
    if (
        len(representation.digits) > MAX_COEFFICIENT_DIGITS
        or abs(int(representation.exponent)) > MAX_ABSOLUTE_EXPONENT
    ):
        raise PositionSizeError(f"{name} exceeds the Decimal representation limit", code, named)
    if value <= 0:
        raise PositionSizeError(f"{name} must be a positive finite Decimal", code, named)
    return value


def _validate(request: PositionSizeRequest, spec: SymbolSpec) -> list[Decimal]:
    values = [
        check_positive_decimal(
            getattr(spec, field.name), field.name, "specs_invalid", names_request_field=False
        )
        for field in fields(spec)
    ]
    values.extend(
        (
            check_positive_decimal(request.entry, "entry"),
            check_positive_decimal(request.balance, "balance"),
        )
    )
    for name in ("sl_price", "sl_points", "risk_percent", "risk_amount"):
        value = getattr(request, name)
        if value is not None:
            values.append(check_positive_decimal(value, name))
    if request.direction not in ("buy", "sell"):
        raise PositionSizeError("direction must be buy or sell", "validation_error", ("direction",))
    if (request.sl_price is None) == (request.sl_points is None):
        raise PositionSizeError(
            "Specify exactly one of sl_price and sl_points",
            "validation_error",
            ("sl_price", "sl_points"),
        )
    if (request.risk_percent is None) == (request.risk_amount is None):
        raise PositionSizeError(
            "Specify exactly one of risk_percent and risk_amount",
            "validation_error",
            ("risk_percent", "risk_amount"),
        )
    if spec.volume_min > spec.volume_max:
        raise PositionSizeError("volume_min must not exceed volume_max", "specs_invalid")
    return values


def _stop(request: PositionSizeRequest, spec: SymbolSpec) -> tuple[Decimal, Decimal]:
    side = Decimal(1) if request.direction == "buy" else Decimal(-1)
    if request.sl_price is not None:
        stop = request.sl_price
    elif request.sl_points is not None:
        stop = request.entry - side * request.sl_points * spec.point
    else:
        raise PositionSizeError(
            "Specify sl_price or sl_points", "validation_error", ("sl_price", "sl_points")
        )
    if stop <= 0 or side * (request.entry - stop) <= 0:
        raise PositionSizeError("SL must be positive and on the loss side of entry", "invalid_stop")
    off_grid = tuple(
        name
        for name, price in (("entry", request.entry), ("sl_price", stop))
        if price % spec.tick_size
    )
    if off_grid:
        raise PositionSizeError(
            "entry and SL must be on the tick-size grid", "off_tick_grid", off_grid
        )
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
        raise PositionSizeError("TP targets must be positive", "invalid_targets")
    return target


def _calculate(request: PositionSizeRequest, spec: SymbolSpec) -> PositionSizeResult:
    if spec.volume_min % spec.volume_step or spec.volume_max % spec.volume_step:
        raise PositionSizeError(
            "Volume limits must be on the zero-based step grid", "specs_invalid"
        )
    stop, distance = _stop(request, spec)
    budget = request.risk_amount
    if budget is None:
        if request.risk_percent is None:
            raise PositionSizeError(
                "Specify risk_percent or risk_amount",
                "validation_error",
                ("risk_percent", "risk_amount"),
            )
        budget = request.balance * request.risk_percent / 100
    # Both prices are on-grid, so tick count and per-lot loss are exact.
    loss_per_lot = (distance // spec.tick_size) * spec.tick_value_loss
    # Integer division avoids a rounded quotient crossing a volume boundary.
    steps = min(budget // (loss_per_lot * spec.volume_step), spec.volume_max // spec.volume_step)
    volume = steps * spec.volume_step
    if volume < spec.volume_min:
        raise PositionSizeError(
            "Risk budget cannot support the minimum volume",
            "below_min_volume",
            min_volume_risk=spec.volume_min * loss_per_lot,
        )
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
    """Size within 64 coefficient digits and stored exponents from -64 to 64.

    Raises PositionSizeError (a ValueError) with a stable `code` for every rejection.
    """
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
        raise PositionSizeError(
            "Sizing data exceeds the Decimal working precision limit", "validation_error"
        )
    try:
        with localcontext() as context:
            context.prec = max(28, precision)
            return _calculate(request, spec)
    except DecimalException as exc:
        raise PositionSizeError(
            "Sizing data exceeds Decimal arithmetic limits", "validation_error"
        ) from exc

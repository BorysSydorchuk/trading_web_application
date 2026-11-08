"""Prospective tick-risk oracles; all specs are synthetic, never broker evidence."""

from dataclasses import replace
from decimal import Decimal
from typing import Any, Literal

import pytest

from app.domain.position_size import (
    PositionSizeRequest,
    SymbolSpec,
    calculate_position_size,
)

D = Decimal


@pytest.fixture
def spec() -> SymbolSpec:
    return SymbolSpec(
        point=D("0.01"),
        tick_size=D("0.01"),
        tick_value_loss=D("1"),
        volume_min=D("0.01"),
        volume_step=D("0.01"),
        volume_max=D("100"),
    )


@pytest.fixture
def sizing_request() -> PositionSizeRequest:
    return PositionSizeRequest(
        direction="buy", entry=D("100"), balance=D("10000"), sl_price=D("99")
    )


@pytest.mark.parametrize(
    ("symbol", "entry", "stop", "point", "tick", "value", "volume", "risk"),
    [
        ("EURUSD", "1.10000", "1.09800", "0.00001", "0.00001", "1", "0.50", "100"),
        ("GBPUSD", "1.25000", "1.24750", "0.00001", "0.00001", "1", "0.40", "100"),
        ("XAUUSD", "2650", "2646", "0.01", "0.01", "1", "0.25", "100"),
        ("GER40", "19000", "18970", "0.1", "0.5", "2.5", "0.66", "99"),
    ],
)
def test_four_synthetic_symbol_hand_calculated_oracles(
    symbol: str,
    entry: str,
    stop: str,
    point: str,
    tick: str,
    value: str,
    volume: str,
    risk: str,
) -> None:
    # Per-lot losses: 200 USD, 250 USD, 400 USD, 150 USD respectively.
    synthetic = SymbolSpec(
        point=D(point),
        tick_size=D(tick),
        tick_value_loss=D(value),
        volume_min=D("0.01"),
        volume_step=D("0.01"),
        volume_max=D("100"),
    )
    result = calculate_position_size(
        PositionSizeRequest(direction="buy", entry=D(entry), sl_price=D(stop), balance=D("10000")),
        synthetic,
    )
    assert result.volume == D(volume), symbol
    assert result.risk_budget == D("100")
    assert result.actual_risk == D(risk)
    assert result.actual_risk_percent == D(risk) / D("100")
    assert result.actual_risk <= result.risk_budget


@pytest.mark.parametrize("direction", ["buy", "sell"])
def test_price_and_broker_point_inputs_agree_and_tp_follows_direction(
    direction: Literal["buy", "sell"],
    spec: SymbolSpec,
    sizing_request: PositionSizeRequest,
) -> None:
    side = D("1") if direction == "buy" else D("-1")
    by_price = calculate_position_size(
        replace(sizing_request, direction=direction, sl_price=D("100") - side),
        spec,
    )
    by_points = calculate_position_size(
        replace(sizing_request, direction=direction, sl_price=None, sl_points=D("100")),
        spec,
    )
    assert by_price == by_points
    assert by_price.sl_distance == D("1")
    assert by_price.sl_price == D("100") - side
    assert by_price.tp_1_5 == D("100") + side * D("1.5")
    assert by_price.tp_2 == D("100") + side * D("2")
    assert by_price.tp_3 == D("100") + side * D("3")


def test_point_is_not_assumed_to_equal_tick_size(
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    result = calculate_position_size(
        replace(sizing_request, sl_price=None, sl_points=D("10")),
        replace(spec, point=D("0.1"), tick_size=D("0.5"), tick_value_loss=D("2.5")),
    )
    assert result.sl_distance == D("1")
    assert result.volume == D("20")
    assert result.actual_risk == D("100")


@pytest.mark.parametrize(
    ("budget", "volume", "risk"),
    [
        ("99.99", "0.75", "75"),
        ("100", "1", "100"),
        ("100.01", "1", "100"),
    ],
)
def test_arbitrary_step_rounds_down_without_decimal_place_quantization(
    budget: str,
    volume: str,
    risk: str,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    result = calculate_position_size(
        replace(sizing_request, risk_percent=None, risk_amount=D(budget)),
        replace(spec, volume_min=D("0.25"), volume_step=D("0.25")),
    )
    assert result.volume == D(volume)
    assert result.actual_risk == D(risk)
    assert result.actual_risk <= result.risk_budget


def test_maximum_volume_is_capped_then_rounded_down(
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    result = calculate_position_size(
        replace(sizing_request, risk_percent=D("10")),
        replace(spec, volume_min=D("0.25"), volume_step=D("0.25"), volume_max=D("1")),
    )
    assert result.volume == D("1")
    assert result.actual_risk == D("100")
    assert result.actual_risk_percent == D("1")


@pytest.mark.parametrize("budget", ["0.000001", "0.99999999999999999999999999"])
def test_budget_below_minimum_never_rounds_up(
    budget: str,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match="Risk budget cannot support the minimum volume"):
        calculate_position_size(
            replace(sizing_request, risk_percent=None, risk_amount=D(budget)), spec
        )


def test_exact_minimum_volume_is_allowed(
    sizing_request: PositionSizeRequest, spec: SymbolSpec
) -> None:
    result = calculate_position_size(
        replace(sizing_request, risk_percent=None, risk_amount=D("1")), spec
    )
    assert result.volume == D("0.01")
    assert result.actual_risk == D("1")


def test_percent_and_money_methods_use_effective_balance_passed_by_caller(
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    percent = calculate_position_size(
        replace(sizing_request, balance=D("20000"), risk_percent=D("0.5")), spec
    )
    money = calculate_position_size(
        replace(sizing_request, balance=D("20000"), risk_percent=None, risk_amount=D("100")),
        spec,
    )
    assert percent == money
    assert money.actual_risk_percent == D("0.5")


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"sl_price": None}, "Specify exactly one of sl_price and sl_points"),
        ({"sl_points": D("100")}, "Specify exactly one of sl_price and sl_points"),
        ({"sl_price": D("100")}, "SL must be positive and on the loss side of entry"),
        ({"sl_price": D("101")}, "SL must be positive and on the loss side of entry"),
        ({"direction": "sell", "sl_price": D("99")}, "SL must be positive and on the loss side"),
        ({"direction": "hold"}, "direction must be buy or sell"),
        ({"entry": D("0")}, "entry must be a positive finite Decimal"),
        ({"entry": D("-1")}, "entry must be a positive finite Decimal"),
        ({"sl_price": D("-1")}, "sl_price must be a positive finite Decimal"),
        ({"balance": D("0")}, "balance must be a positive finite Decimal"),
        ({"balance": D("-1")}, "balance must be a positive finite Decimal"),
        ({"risk_percent": None}, "Specify exactly one of risk_percent and risk_amount"),
        ({"risk_amount": D("100")}, "Specify exactly one of risk_percent and risk_amount"),
        ({"risk_percent": D("0")}, "risk_percent must be a positive finite Decimal"),
        ({"risk_percent": D("-1")}, "risk_percent must be a positive finite Decimal"),
        ({"risk_percent": None, "risk_amount": D("0")}, "risk_amount must be a positive finite"),
        ({"risk_percent": None, "risk_amount": D("-1")}, "risk_amount must be a positive finite"),
        ({"sl_price": None, "sl_points": D("0")}, "sl_points must be a positive finite Decimal"),
        ({"sl_price": None, "sl_points": D("-1")}, "sl_points must be a positive finite Decimal"),
        ({"sl_price": None, "sl_points": D("10001")}, "SL must be positive and on the loss side"),
    ],
)
def test_invalid_requests_are_rejected(
    changes: dict[str, Any],
    error: str,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match=error):
        calculate_position_size(replace(sizing_request, **changes), spec)


@pytest.mark.parametrize(
    "field", ["point", "tick_size", "tick_value_loss", "volume_min", "volume_step", "volume_max"]
)
@pytest.mark.parametrize("value", [D("0"), D("-1"), D("NaN"), D("Infinity"), D("-Infinity")])
def test_invalid_spec_numbers_are_rejected(
    field: str,
    value: Decimal,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match=rf"{field} must be a positive finite Decimal"):
        calculate_position_size(sizing_request, replace(spec, **{field: value}))


def test_reversed_volume_limits_are_rejected(
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match="volume_min must not exceed volume_max"):
        calculate_position_size(sizing_request, replace(spec, volume_min=D("101")))


@pytest.mark.parametrize("field", ["entry", "balance", "sl_price", "risk_percent"])
@pytest.mark.parametrize("value", [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity")])
def test_nonfinite_request_numbers_are_rejected(
    field: str,
    value: Decimal,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    changes: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=rf"{field} must be a positive finite Decimal"):
        calculate_position_size(replace(sizing_request, **changes), spec)


@pytest.mark.parametrize("field", ["sl_points", "risk_amount"])
@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), D("-Infinity")])
def test_nonfinite_optional_numbers_are_rejected(
    field: str,
    value: Decimal,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    changes: dict[str, Any] = (
        {"sl_price": None, "sl_points": value}
        if field == "sl_points"
        else {"risk_percent": None, "risk_amount": value}
    )
    with pytest.raises(ValueError, match=rf"{field} must be a positive finite Decimal"):
        calculate_position_size(replace(sizing_request, **changes), spec)


def test_decimal_arithmetic_preserves_a_fractional_cent_budget(
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    result = calculate_position_size(
        replace(sizing_request, risk_percent=None, risk_amount=D("0.3")),
        replace(spec, tick_value_loss=D("0.1")),
    )
    assert result.volume == D("0.03")
    assert result.actual_risk == D("0.3")
    assert result.actual_risk_percent == D("0.003")


@pytest.mark.parametrize(
    "changes",
    [
        {"entry": D("100.001")},
        {"sl_price": D("99.001")},
        {"sl_price": None, "sl_points": D("0.5")},
    ],
)
def test_off_tick_prices_are_rejected(
    changes: dict[str, Any],
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match="entry and SL must be on the tick-size grid"):
        calculate_position_size(replace(sizing_request, **changes), spec)


@pytest.mark.parametrize(
    ("direction", "stop", "targets"),
    [
        ("buy", "99.97", ("100.05", "100.06", "100.09")),
        ("sell", "100.03", ("99.95", "99.94", "99.91")),
    ],
)
def test_tp_rounds_away_from_entry_to_preserve_minimum_reward_ratio(
    direction: Literal["buy", "sell"],
    stop: str,
    targets: tuple[str, str, str],
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    result = calculate_position_size(
        replace(sizing_request, direction=direction, sl_price=D(stop)), spec
    )
    assert (result.tp_1_5, result.tp_2, result.tp_3) == tuple(D(target) for target in targets)


def test_sell_with_nonpositive_target_is_rejected(
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match="TP targets must be positive"):
        calculate_position_size(
            replace(sizing_request, direction="sell", entry=D("1"), sl_price=D("2")),
            spec,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"volume_min": D("0.03"), "volume_step": D("0.02")},
        {"volume_max": D("1.1"), "volume_step": D("0.25"), "volume_min": D("0.25")},
    ],
)
def test_volume_limits_must_use_the_zero_based_step_grid(
    changes: dict[str, Decimal],
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    with pytest.raises(ValueError, match="Volume limits must be on the zero-based step grid"):
        calculate_position_size(sizing_request, replace(spec, **changes))


@pytest.mark.parametrize("point", [D("1e-1000000000"), D("1e1000000000"), D("1" * 65)])
def test_decimal_representation_limits_reject_before_creating_arithmetic_context(
    point: Decimal,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_context() -> None:
        raise AssertionError("Representation validation must precede arithmetic context allocation")

    monkeypatch.setattr("app.domain.position_size.localcontext", forbidden_context)
    with pytest.raises(ValueError, match=r"representation|precision|limit"):
        calculate_position_size(
            replace(sizing_request, balance=D("3000"), risk_amount=D("100"), risk_percent=None),
            replace(spec, point=point),
        )


@pytest.mark.parametrize("point", [D("1" * 64), D("1e-64"), D("1e64")])
def test_decimal_representation_boundary_is_accepted_for_unused_point(
    point: Decimal,
    sizing_request: PositionSizeRequest,
    spec: SymbolSpec,
) -> None:
    result = calculate_position_size(sizing_request, replace(spec, point=point))
    assert result.volume == D("1")
    assert result.actual_risk == D("100")

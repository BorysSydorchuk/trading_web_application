"""Sizing with the real FundedNext specs (ROADMAP M5).

Specs as MT5 reported them for account 11459118 («FN Stellar Funded», USD) at the sync of
2026-11-12 16:11 UTC; account size 10 000, so 1 % = 100.00 USD (M5-10). GER30 (canonical
GER40) is EUR-profit: loss per tick = tick 0.01 x contract 10 x EURUSD ask 1.10609 (M5-09);
MT5 order_calc_profit gave 0.11060908 in the same cycle. The GER40 case is Borys's M5-07
owner check (lot 0.13, actual risk 92.89 USD).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain import fx
from app.domain.position_size import PositionSizeRequest, SymbolSpec, calculate_position_size

D = Decimal

ACCOUNT_SIZE = D("10000.00")
CENT = D("0.01")

EURUSD = SymbolSpec(
    point=D("0.00001"),
    tick_size=D("0.00001"),
    tick_value_loss=D("1"),
    volume_min=D("0.01"),
    volume_step=D("0.01"),
    volume_max=D("40"),
)
GBPUSD = EURUSD
XAUUSD = SymbolSpec(
    point=D("0.01"),
    tick_size=D("0.01"),
    tick_value_loss=D("1"),
    volume_min=D("0.01"),
    volume_step=D("0.01"),
    volume_max=D("50"),
)
GER30_TICK_SIZE = D("0.01")
GER30_CONTRACT_SIZE = D("10")
EURUSD_ASK = D("1.10609")
GER30_MT5_CHECK = D("0.11060908")


def _ger30_spec() -> SymbolSpec:
    rate_value = fx.loss_per_tick_from_rate(GER30_TICK_SIZE, GER30_CONTRACT_SIZE, EURUSD_ASK)
    loss_per_tick, _source = fx.choose_loss_per_tick(rate_value, GER30_MT5_CHECK)
    return SymbolSpec(
        point=D("0.01"),
        tick_size=GER30_TICK_SIZE,
        tick_value_loss=loss_per_tick,
        volume_min=D("0.01"),
        volume_step=D("0.01"),
        volume_max=D("40"),
    )


def test_ger30_loss_per_tick_uses_rate_value_matching_mt5_check() -> None:
    rate_value = fx.loss_per_tick_from_rate(GER30_TICK_SIZE, GER30_CONTRACT_SIZE, EURUSD_ASK)

    value, source = fx.choose_loss_per_tick(rate_value, GER30_MT5_CHECK)

    assert rate_value == D("0.110609")
    assert (value, source) == (D("0.110609"), "rate")
    # never the stale MT5 tick_value 0.12
    assert value != D("0.12")


@pytest.mark.parametrize(
    ("name", "spec", "request_", "volume", "actual_risk"),
    [
        (
            # 180 points x 1 USD = 180 per lot; 100 / 180 = 0.5556 -> 0.55
            "EURUSD buy, SL price",
            EURUSD,
            PositionSizeRequest(
                direction="buy", entry=D("1.10609"), sl_price=D("1.10429"), balance=ACCOUNT_SIZE
            ),
            D("0.55"),
            D("99.00"),
        ),
        (
            # 200 points x 1 USD = 200 per lot; 100 / 200 = 0.50
            "GBPUSD sell, SL points",
            GBPUSD,
            PositionSizeRequest(
                direction="sell", entry=D("1.31500"), sl_points=D("200"), balance=ACCOUNT_SIZE
            ),
            D("0.50"),
            D("100.00"),
        ),
        (
            # 1225 ticks x 1 USD = 1225 per lot; 100 / 1225 = 0.0816 -> 0.08
            "XAUUSD buy, SL price",
            XAUUSD,
            PositionSizeRequest(
                direction="buy", entry=D("4105.50"), sl_price=D("4093.25"), balance=ACCOUNT_SIZE
            ),
            D("0.08"),
            D("98.00"),
        ),
        (
            # 6460 ticks x 0.110609 = 714.53414 per lot; 100 / 714.53414 = 0.13995 -> 0.13
            "GER40 (GER30) buy, owner check M5-07",
            _ger30_spec(),
            PositionSizeRequest(
                direction="buy", entry=D("26478.80"), sl_price=D("26414.20"), balance=ACCOUNT_SIZE
            ),
            D("0.13"),
            D("92.89"),
        ),
    ],
)
def test_real_spec_sizing_at_one_percent_of_account_size(
    name: str,
    spec: SymbolSpec,
    request_: PositionSizeRequest,
    volume: Decimal,
    actual_risk: Decimal,
) -> None:
    result = calculate_position_size(request_, spec)

    assert result.risk_budget == D("100"), name
    assert result.volume == volume, name
    assert result.actual_risk.quantize(CENT) == actual_risk, name
    assert result.actual_risk <= result.risk_budget, name
    # one more volume step would exceed the budget (rounded down, never up)
    one_more = (result.volume + spec.volume_step) / result.volume * result.actual_risk
    assert one_more > result.risk_budget, name

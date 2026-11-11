"""Trade risk for cross-currency specs (docs/api.md M5-09 "Trade metrics fallback").

New keyword of ``app.domain.metrics.risk_amount``: ``loss_per_tick`` (account currency per tick
per lot). When given it replaces ``tick_value`` in the fallback
``|entry - SL| / tick_size * loss_per_tick * volume``. The realised-P&L path is unchanged.

New keywords of ``app.services.sync.trade_values``: ``account_currency: str | None = None`` and
``fx_loss_per_tick: Decimal | None = None``. When the spec's profit currency differs from
``account_currency`` (case-insensitive) the fallback uses ``fx_loss_per_tick`` and NEVER the
spec's tick_value (None -> risk None). Without ``account_currency`` behaviour is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.config_files import get_rules
from app.domain.metrics import risk_amount
from app.domain.trade_builder import BuiltTrade
from app.models.enums import Direction, InitialSlSource
from app.mt5.types import RawSymbolSpec
from app.services.sync import trade_values

D = Decimal
OPEN = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)

# Open GER30 buy, 0.13 lot, 6460 ticks to SL; real EURUSD gives 0.11091, stale MT5 value 0.12.
OPEN_KW: dict[str, Any] = {
    "entry_price": D("26478.80"),
    "initial_sl": D("26414.20"),
    "volume": D("0.13"),
    "tick_size": D("0.01"),
}


# --- risk_amount ---------------------------------------------------------------------------------


def test_open_cross_currency_trade_risk_comes_from_the_rate_value() -> None:
    # 6460 * 0.11091 * 0.13 = 93.1429 -> 93.14 (tick_value 0.12 would give 100.78).
    assert risk_amount(**OPEN_KW, loss_per_tick=D("0.11091")) == D("93.14")


def test_loss_per_tick_wins_over_tick_value() -> None:
    result = risk_amount(**OPEN_KW, tick_value=D("0.12"), loss_per_tick=D("0.11091"))

    assert result == D("93.14")


def test_without_loss_per_tick_tick_value_is_still_used() -> None:
    assert risk_amount(**OPEN_KW, tick_value=D("0.12")) == D("100.78")


def test_no_loss_per_tick_and_no_tick_value_is_none() -> None:
    assert risk_amount(**OPEN_KW) is None


def test_breakeven_cross_currency_trade_uses_loss_per_tick() -> None:
    result = risk_amount(
        **OPEN_KW,
        exit_price=D("26478.80"),
        exit_volume=D("0.13"),
        gross_pnl=D("0"),
        loss_per_tick=D("0.11091"),
    )

    assert result == D("93.14")


def test_realised_path_is_unchanged_by_loss_per_tick() -> None:
    # Real GER30 trade 1: 167.65 / 136.89 * 82.51 = 101.05; neither 0.12 nor the rate matter.
    kwargs: dict[str, Any] = {
        "entry_price": D("25572.61"),
        "initial_sl": D("25490.10"),
        "volume": D("0.11"),
        "exit_price": D("25709.50"),
        "exit_volume": D("0.11"),
        "gross_pnl": D("167.65"),
        "tick_size": D("0.01"),
    }

    assert risk_amount(**kwargs) == D("101.05")
    assert risk_amount(**kwargs, loss_per_tick=D("0.11091")) == D("101.05")
    assert risk_amount(**kwargs, tick_value=D("0.12"), loss_per_tick=D("0.11091")) == D("101.05")


def test_zero_distance_is_zero_risk_with_loss_per_tick() -> None:
    kwargs = OPEN_KW | {"initial_sl": D("26478.80")}

    assert risk_amount(**kwargs, loss_per_tick=D("0.11091")) == D("0.00")


# --- trade_values (the sync's caller) ------------------------------------------------------------


def ger30_spec() -> RawSymbolSpec:
    return RawSymbolSpec(
        name="GER30",
        digits=2,
        contract_size=D("10"),
        tick_size=D("0.01"),
        tick_value=D("0.12"),
        volume_min=D("0.01"),
        volume_step=D("0.01"),
        volume_max=D("100"),
        currency_profit="EUR",
        currency_margin="EUR",
        point=D("0.01"),
        tick_value_loss=D("0.12"),
    )


def built(*, closed: bool) -> BuiltTrade:
    """Open 0.13 lot buy (entry 26478.80, SL 26414.20) or the real closed GER30 trade 1."""
    if closed:
        return BuiltTrade(
            position_id=1,
            symbol="GER30",
            direction=Direction.BUY,
            open_time=OPEN,
            close_time=OPEN + timedelta(hours=1),
            duration_seconds=3600,
            entry_price=D("25572.61"),
            exit_price=D("25709.50"),
            volume=D("0.11"),
            open_volume=D("0"),
            exit_volume=D("0.11"),
            commission=D("0"),
            swap=D("0"),
            gross_pnl=D("167.65"),
            net_pnl=D("167.65"),
            exit_deals=(),
            initial_sl=D("25490.10"),
            initial_sl_source=InitialSlSource.DEAL,
            last_sl=D("25490.10"),
            tp=None,
        )
    return BuiltTrade(
        position_id=2,
        symbol="GER30",
        direction=Direction.BUY,
        open_time=OPEN,
        close_time=None,
        duration_seconds=None,
        entry_price=D("26478.80"),
        exit_price=None,
        volume=D("0.13"),
        open_volume=D("0.13"),
        exit_volume=D("0"),
        commission=D("0"),
        swap=D("0"),
        gross_pnl=D("0"),
        net_pnl=D("0"),
        exit_deals=(),
        initial_sl=D("26414.20"),
        initial_sl_source=InitialSlSource.POSITION,
        last_sl=D("26414.20"),
        tp=None,
    )


def values(trade: BuiltTrade, **extra: Any) -> dict[str, Any]:
    return trade_values(
        trade,
        None,
        deals=[],
        balance=D("10401.70"),
        spec=ger30_spec(),
        rules=get_rules(),
        symbol="GER40",
        **extra,
    )


def test_trade_values_open_cross_currency_trade_uses_the_rate_not_tick_value() -> None:
    result = values(built(closed=False), account_currency="USD", fx_loss_per_tick=D("0.11091"))

    assert result["risk_amount"] == D("93.14")


def test_trade_values_cross_currency_without_a_rate_has_no_risk() -> None:
    result = values(built(closed=False), account_currency="USD", fx_loss_per_tick=None)

    assert result["risk_amount"] is None
    assert result["risk_pct"] is None


def test_trade_values_account_currency_is_compared_case_insensitively() -> None:
    result = values(built(closed=False), account_currency="usd", fx_loss_per_tick=D("0.11091"))

    assert result["risk_amount"] == D("93.14")


def test_trade_values_same_currency_spec_still_uses_tick_value() -> None:
    result = values(built(closed=False), account_currency="EUR", fx_loss_per_tick=D("0.5"))

    assert result["risk_amount"] == D("100.78")  # 6460 * 0.12 * 0.13


def test_trade_values_closed_trade_keeps_its_realised_risk() -> None:
    with_rate = values(built(closed=True), account_currency="USD", fx_loss_per_tick=D("0.11091"))
    without_rate = values(built(closed=True), account_currency="USD", fx_loss_per_tick=None)

    assert with_rate["risk_amount"] == D("101.05")
    assert without_rate["risk_amount"] == D("101.05")


def test_trade_values_without_account_currency_behaves_as_before() -> None:
    assert values(built(closed=False))["risk_amount"] == D("100.78")

"""Shared synthetic MT5 records for tests (not recorded broker data)."""

from decimal import Decimal

from app.mt5.types import RawSymbolSpec


def legacy_spec() -> RawSymbolSpec:
    return RawSymbolSpec(
        name="GER40.cash",
        digits=1,
        contract_size=Decimal("1"),
        tick_size=Decimal("0.5"),
        tick_value=Decimal("2"),
        volume_min=Decimal("0.01"),
        volume_step=Decimal("0.01"),
        volume_max=Decimal("100"),
        currency_profit="EUR",
        currency_margin="EUR",
    )

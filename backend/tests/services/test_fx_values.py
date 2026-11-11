"""Shared trade-risk per-tick rule (app.services.fx_values, docs/api.md M5-09) and the FX spec
filter of the sync (app.services.fx_sync.cross_specs). Pure: transient rows, no DB."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import FxRate
from app.mt5.types import RawSymbolSpec
from app.services.fx_sync import cross_specs
from app.services.fx_values import RiskTickValues, cross_loss_per_tick, tick_values

D = Decimal
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def row(rate: str) -> FxRate:
    return FxRate(
        account_id=1, from_currency="EUR", to_currency="USD", pair="EURUSD", inverted=False,
        bid=D(rate), ask=D(rate), rate=D(rate), rate_at=T0, synced_at=T0,
    )  # fmt: skip


def raw(**kw: object) -> RawSymbolSpec:
    fields: dict[str, object] = {
        "name": "GER30", "digits": 2, "contract_size": D(10), "tick_size": D("0.01"),
        "tick_value": D("0.12"), "volume_min": D("0.01"), "volume_step": D("0.01"),
        "volume_max": D(100), "currency_profit": "EUR", "currency_margin": "EUR",
    }  # fmt: skip
    return RawSymbolSpec(**(fields | kw))  # type: ignore[arg-type]


def test_real_case_from_the_rate() -> None:
    assert cross_loss_per_tick(1, "GER30", D("0.01"), D(10), row("1.1091"), None) == D("0.11091")


def test_no_rate_row_is_none() -> None:
    assert cross_loss_per_tick(1, "GER30", D("0.01"), D(10), None, D("0.12")) is None


def test_disagreeing_check_wins_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        value = cross_loss_per_tick(1, "GER30", D("0.01"), D(10), row("1.1091"), D("0.12"))

    assert value == D("0.12")
    assert any("0.12" in r.getMessage() and "0.11091" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("tick_size", "contract_size", "rate"),
    [
        (D(0), D(10), "1.1091"),
        (D("0.01"), D("-1"), "1.1091"),
        (D("NaN"), D(10), "1.1091"),
        (D("0.01"), D("Infinity"), "1.1091"),
        (D("0.01"), D(10), "0"),
    ],
)
def test_unusable_values_are_a_warning_and_none(
    caplog: pytest.LogCaptureFixture, tick_size: Decimal, contract_size: Decimal, rate: str
) -> None:
    with caplog.at_level(logging.WARNING):
        value = cross_loss_per_tick(1, "GER30", tick_size, contract_size, row(rate), None)

    assert value is None
    assert any("GER30" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_tick_values_same_currency_keeps_tick_value() -> None:
    assert tick_values("usd", D("1.00"), "USD", D("9")) == RiskTickValues(D("1.00"), None)


def test_tick_values_cross_currency_never_uses_tick_value() -> None:
    assert tick_values("EUR", D("0.12"), "USD", D("0.11091")) == RiskTickValues(None, D("0.11091"))
    assert tick_values("EUR", D("0.12"), "USD", None) == RiskTickValues(None, None)


def test_tick_values_without_account_currency_keeps_tick_value() -> None:
    assert tick_values("EUR", D("0.12"), None, None) == RiskTickValues(D("0.12"), None)


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"tick_size": D("NaN")}, "tick_size"),
        ({"tick_size": D("-Infinity")}, "tick_size"),
        ({"contract_size": D("Infinity")}, "contract_size"),
        ({"contract_size": D(0)}, "contract_size"),
        ({"currency_profit": "  "}, "currency"),
    ],
)
def test_cross_specs_skip_unusable_specs_with_a_warning(
    caplog: pytest.LogCaptureFixture, overrides: dict[str, object], needle: str
) -> None:
    good = raw(name="FRA40")
    with caplog.at_level(logging.WARNING):
        result = cross_specs([raw(**overrides), good], "USD")

    assert result == [good]
    assert any("GER30" in r.getMessage() and needle in r.getMessage() for r in caplog.records)

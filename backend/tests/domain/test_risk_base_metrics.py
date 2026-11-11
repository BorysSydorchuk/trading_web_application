"""M5-10: trade risk % and P&L % divide by the account size, not balance_at_open.

Names the backend must provide (docs/api.md "M5-10"):
- ``app.domain.metrics.risk_pct(risk, account_size)`` and ``pnl_pct(net_pnl, account_size)``
  (the second parameter is renamed ``account_size``; tests pass it by keyword).
- ``app.services.sync.trade_values(..., account_size: Decimal | None)`` keyword (required):
  percent fields use it; ``balance`` (the live balance) still feeds ``balance_at_open``.
  ``account_size`` None / not positive -> both percents None.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.config_files import get_rules
from app.domain.metrics import pnl_pct, risk_pct
from app.services.sync import trade_values
from tests.domain.test_metrics_fx import built, ger30_spec

D = Decimal
TEN_K = Decimal("10000")


def test_risk_pct_divides_by_the_account_size() -> None:
    assert risk_pct(D("100.00"), account_size=D("10000")) == D("1.0000")


def test_pnl_pct_divides_by_the_account_size() -> None:
    assert pnl_pct(D("-205.60"), account_size=D("50000")) == D("-0.4112")


@pytest.mark.parametrize("size", [None, D("0"), D("-5"), D("NaN")])
def test_no_usable_size_gives_none(size: Decimal | None) -> None:
    assert risk_pct(D("100"), account_size=size) is None
    assert pnl_pct(D("100"), account_size=size) is None


def test_none_amounts_give_none() -> None:
    assert risk_pct(None, account_size=D("10000")) is None
    assert pnl_pct(None, account_size=D("10000")) is None


def test_rounding_is_half_up_at_four_decimals_also_for_negative_pnl() -> None:
    assert risk_pct(D("0.01"), account_size=D("20000")) == D("0.0001")  # 0.00005
    assert pnl_pct(D("0.01"), account_size=D("20000")) == D("0.0001")
    assert pnl_pct(D("-0.01"), account_size=D("20000")) == D("-0.0001")


# --- trade_values (the sync's caller) ------------------------------------------------------------


def usd_spec() -> Any:
    return replace(
        ger30_spec(),
        name="XAUUSD",
        currency_profit="USD",
        currency_margin="USD",
        tick_value=D("1"),
        tick_value_loss=D("1"),
    )


def open_trade_risking_100() -> Any:
    # 100.00 - 99.00 = 100 ticks of 0.01 x 1 USD x 1 lot = 100.00
    return replace(
        built(closed=False),
        symbol="XAUUSD",
        entry_price=D("100.00"),
        initial_sl=D("99.00"),
        last_sl=D("99.00"),
        volume=D("1"),
        open_volume=D("1"),
    )


def values(balance: str, *, size: Decimal | None = TEN_K, **extra: Any) -> dict[str, Any]:
    return trade_values(
        open_trade_risking_100(),
        None,
        deals=[],
        balance=D(balance),
        spec=usd_spec(),
        rules=get_rules(),
        account_currency="USD",
        account_size=size,
        **extra,
    )


@pytest.mark.parametrize("balance", ["10401.70", "9857.58"])
def test_risk_100_on_a_10000_account_is_one_percent_above_and_below_the_balance(
    balance: str,
) -> None:
    result = values(balance)

    assert result["risk_amount"] == D("100.00")
    assert result["risk_pct"] == D("1.0000")
    assert result["balance_at_open"] == D(balance)  # still stored, information only


def test_closed_trade_pnl_pct_uses_the_size() -> None:
    trade = replace(
        built(closed=True),
        symbol="XAUUSD",
        net_pnl=D("250.00"),
    )

    result = trade_values(
        trade,
        None,
        deals=[],
        balance=D("10401.70"),
        spec=usd_spec(),
        rules=get_rules(),
        account_currency="USD",
        account_size=D("10000"),
    )

    assert result["pnl_pct"] == D("2.5000")


def test_open_trade_has_no_pnl_pct() -> None:
    assert values("10401.70")["pnl_pct"] is None


@pytest.mark.parametrize("size", [None, D("0"), D("NaN")])
def test_missing_size_leaves_percents_empty_but_keeps_risk_amount(size: Decimal | None) -> None:
    result = values("10401.70", size=size)

    assert result["risk_amount"] == D("100.00")
    assert result["risk_pct"] is None
    assert result["pnl_pct"] is None


def test_trade_values_requires_the_account_size_keyword() -> None:
    parameter = inspect.signature(trade_values).parameters["account_size"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty

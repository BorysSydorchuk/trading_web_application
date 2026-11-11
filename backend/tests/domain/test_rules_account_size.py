"""M5-10: rule percentages are % of the account size (PRD 6.9), not of a balance.

``RuleTradeInput`` gets ``account_size: Decimal | None`` (the account's reference_balance) and
loses ``balance_at_open`` (no longer an input of any rule). Stops: running closed P&L of the
period / account_size x 100, sticky replay unchanged; account_size None / not positive -> no
stop violation. ``max_risk_pct`` compares the (already account-size based) ``risk_pct``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.rules import RuleTradeInput, Violation, evaluate
from tests.domain.test_rules import RULES, D, keys, rules, tr, utc


def _details(trade_key: str, trade: RuleTradeInput, ctx: list[RuleTradeInput]) -> list[Violation]:
    found = [v for v in evaluate(trade, ctx, RULES, None) if v.rule_key == trade_key]
    return found


SIZE = "10000"


def _day(*pnls: str) -> list[RuleTradeInput]:
    return [
        tr(10 + i, utc(11, 2, 7, 5 + 10 * i), utc(11, 2, 7, 10 + 10 * i), p, size=SIZE)
        for i, p in enumerate(pnls)
    ]


def _entry(**kw: Any) -> RuleTradeInput:
    return tr(1, utc(11, 2, 9), size=SIZE, **kw)


def test_daily_stop_minus_3_percent_of_10000_is_minus_300() -> None:
    (v,) = _details("daily_stop_loss_pct", _entry(), _day("-300.00"))

    assert v.details == "day P&L reached -3.00% (-300.00) before entry <= limit -3.0%"


def test_daily_stop_minus_299_99_is_not_flagged() -> None:
    assert _details("daily_stop_loss_pct", _entry(), _day("-299.99")) == []


def test_daily_stop_profit_plus_5_percent_of_10000_is_plus_500() -> None:
    assert _details("daily_stop_profit_pct", _entry(), _day("500.00"))
    assert _details("daily_stop_profit_pct", _entry(), _day("499.99")) == []


def test_daily_stop_is_sticky_with_the_size_base() -> None:
    ctx = _day("-350.00", "+200.00")  # reached -3.50 %, recovered to -1.50 %

    assert _details("daily_stop_loss_pct", _entry(), ctx)


def test_weekly_stops_use_the_account_size() -> None:
    ctx = [
        tr(10, utc(11, 2, 8), utc(11, 2, 9), "-400.00", size=SIZE),  # Mon
        tr(11, utc(11, 3, 8), utc(11, 3, 9), "-200.00", size=SIZE),  # Tue: -6.00 % of week
    ]
    wed = tr(1, utc(11, 4, 8), size=SIZE)

    assert "weekly_stop_loss_pct" in keys(wed, ctx)
    ctx_ok = [ctx[0], tr(11, utc(11, 3, 8), utc(11, 3, 9), "-199.99", size=SIZE)]
    assert "weekly_stop_loss_pct" not in keys(wed, ctx_ok)
    win = [
        tr(10, utc(11, 2, 8), utc(11, 2, 9), "600.00", size=SIZE),
        tr(11, utc(11, 3, 8), utc(11, 3, 9), "400.00", size=SIZE),  # +10.00 %
    ]
    assert "weekly_stop_profit_pct" in keys(wed, win)
    win_ok = [win[0], tr(11, utc(11, 3, 8), utc(11, 3, 9), "399.99", size=SIZE)]
    assert "weekly_stop_profit_pct" not in keys(wed, win_ok)


def test_the_base_is_the_entering_trades_account_size_not_the_pnl() -> None:
    # Same -300.00 P&L: -3.00 % of 10000 flags; -0.30 % of 100000 does not.
    big = tr(1, utc(11, 2, 9), size="100000")
    assert "daily_stop_loss_pct" not in keys(big, _day("-300.00"))
    assert "daily_stop_loss_pct" in keys(_entry(), _day("-300.00"))


@pytest.mark.parametrize("size", [None, "0", "-1"])
def test_no_usable_size_gives_no_stop_violation(size: str | None) -> None:
    trade = tr(1, utc(11, 2, 9), size=size)

    assert not {"daily_stop_loss_pct", "weekly_stop_loss_pct"} & keys(trade, _day("-900.00"))


def test_max_risk_pct_uses_the_given_risk_pct() -> None:
    assert "max_risk_pct" in keys(tr(1, utc(11, 2, 8), size=SIZE, risk_pct=D("1.1001")))
    assert "max_risk_pct" not in keys(tr(1, utc(11, 2, 8), size=SIZE, risk_pct=D("1.1000")))
    assert "max_risk_pct" not in keys(
        tr(1, utc(11, 2, 8), size=SIZE, risk_pct=D("5")), cfg=rules(max_risk_pct={"enabled": False})
    )

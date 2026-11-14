"""Breakeven by R threshold (Borys/PM 2026-11-14, option A).

A trade with a known R and |R| < threshold is «в нуль» (breakeven), never a win or a loss.
Without R the P&L sign decides (> 0 win, < 0 loss, 0 breakeven). The threshold travels on
``DigestTrade.breakeven_r_threshold`` (default 0 = the old P&L-sign rule); the service fills it
from rules.yaml ``breakeven_r_threshold`` (default 0.1). Profit factor stays money-based.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain import digest_metrics as dm

D = Decimal
T = D("0.1")
CLOSE = datetime(2026, 11, 10, 10, tzinfo=UTC)


def trade(
    tid: int, pnl: str, r: str | None, threshold: Decimal = T, account_id: int = 1
) -> dm.DigestTrade:
    return dm.DigestTrade(
        id=tid,
        account_id=account_id,
        symbol="EURUSD",
        close_time=CLOSE.replace(minute=tid),
        net_pnl=D(pnl),
        r_multiple=None if r is None else D(r),
        breakeven_r_threshold=threshold,
    )


@pytest.mark.parametrize(
    ("pnl", "r", "expected"),
    [
        ("-3.00", "-0.05", "breakeven"),  # small loss, |R| < 0.1
        ("4.00", "0.09", "breakeven"),
        ("-10.00", "-0.10", "loss"),  # exactly the threshold is not breakeven
        ("10.00", "0.10", "win"),
        ("0.00", "0.00", "breakeven"),
        ("50.00", "1.0", "win"),
        ("-50.00", "-1.0", "loss"),
        ("5.00", None, "win"),  # no R: P&L sign
        ("-5.00", None, "loss"),
        ("0.00", None, "breakeven"),
    ],
)
def test_outcome_uses_r_threshold_then_pnl_sign(pnl: str, r: str | None, expected: str) -> None:
    assert dm.outcome(trade(1, pnl, r)) == expected


def test_threshold_zero_is_the_old_pnl_sign_rule() -> None:
    assert dm.outcome(trade(1, "-3.00", "-0.05", threshold=D(0))) == "loss"
    assert dm.outcome(trade(1, "4.00", "0.09", threshold=D(0))) == "win"


def test_default_threshold_on_digest_trade_is_zero() -> None:
    t = dm.DigestTrade(
        id=1, account_id=1, symbol="X", close_time=CLOSE, net_pnl=D("-1"), r_multiple=D("-0.01")
    )
    assert dm.outcome(t) == "loss"


def test_metrics_count_small_r_trades_as_breakeven() -> None:
    # wins: 1 (+1R), losses: 1 (-1R), breakeven: 2 (-0.05R, no-R 0 P&L)
    trades = [
        trade(1, "100.00", "1.0"),
        trade(2, "-100.00", "-1.0"),
        trade(3, "-5.00", "-0.05"),
        trade(4, "0.00", None),
    ]

    m = dm.compute_metrics(trades, {1: D("10000")})

    assert (m.wins, m.losses, m.breakeven) == (1, 1, 2)
    assert m.win_rate == D(25)  # 1 / 4 trades
    assert m.avg_win_r == D("1.0")
    assert m.avg_loss_r == D("-1.0")  # the -0.05R breakeven is not averaged in
    # profit factor stays money-based: 100 / (100 + 5)
    assert m.profit_factor == D("100") / D("105")


def test_breakdown_win_rate_uses_the_same_rule() -> None:
    trades = [trade(1, "100.00", "1.0"), trade(2, "3.00", "0.05")]

    groups = dm.breakdown(trades, "symbol").groups

    assert groups[0].win_rate == D(50)

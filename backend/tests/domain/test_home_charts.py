"""M8-14 Home charts: equity curve, P&L by day, rolling win rate / average R (pure)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.home_charts import ChartTrade, daily_pnl, equity, pct, rolling

D = Decimal
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)  # Tue 10:00 Brussels


def trade(
    i: int, pnl: str, r: str | None, *, hours: float = 0, excluded: bool = False
) -> ChartTrade:
    return ChartTrade(
        id=i,
        account_id=1,
        close_time=T0 + timedelta(hours=hours),
        net_pnl=D(pnl),
        r_multiple=None if r is None else D(r),
        excluded=excluded,
    )


def test_equity_starts_at_zero_at_the_range_start_and_runs_through_every_trade() -> None:
    trades = [trade(2, "-50", "-0.5", hours=2), trade(1, "100", "1", hours=1)]

    points = equity(trades, date(2026, 11, 9))

    assert [(p.cum_pnl) for p in points] == [D(0), D(100), D(50)]
    assert points[0].time == datetime(2026, 11, 8, 23, 0, tzinfo=UTC)  # Mon 00:00 Brussels


def test_equity_includes_excluded_trades_real_money() -> None:
    points = equity(
        [trade(1, "100", "1"), trade(2, "-30", "-0.3", hours=1, excluded=True)], date(2026, 11, 9)
    )
    assert points[-1].cum_pnl == D(70)


def test_daily_pnl_groups_by_brussels_date() -> None:
    late = ChartTrade(
        3, 1, datetime(2026, 11, 10, 23, 30, tzinfo=UTC), D("20"), None, False
    )  # Wed 00:30
    days = daily_pnl([trade(1, "100", "1"), trade(2, "-40", "-0.4", hours=3), late])

    assert [(d.day, d.net_pnl, d.trades) for d in days] == [
        (date(2026, 11, 10), D(60), 2),
        (date(2026, 11, 11), D(20), 1),
    ]


def test_rolling_window_skips_excluded_trades_and_uses_the_breakeven_rule() -> None:
    trades = [
        trade(1, "100", "1.0", hours=1),
        trade(2, "-100", "-1.0", hours=2),
        trade(3, "5", "0.05", hours=3),  # |R| < 0.1: breakeven, not a win
        trade(4, "-500", "-5", hours=4, excluded=True),
        trade(5, "200", "2.0", hours=5),
    ]

    points = rolling(trades, window=3, breakeven_r=D("0.1"))

    assert [p.trade_id for p in points] == [1, 2, 3, 5]
    assert [(p.n, p.win_rate, p.avg_r) for p in points] == [
        (1, D("100.0000"), D("1.0000")),
        (2, D("50.0000"), D("0.0000")),
        (3, D("33.3333"), D("0.0167")),
        (3, D("33.3333"), D("0.3500")),  # window = trades 2, 3, 5
    ]


def test_rolling_average_r_ignores_trades_without_r() -> None:
    points = rolling(
        [trade(1, "100", None), trade(2, "-50", "-1", hours=1)], window=20, breakeven_r=D(0)
    )
    assert points[0].avg_r is None
    assert points[1].avg_r == D("-1.0000")
    assert points[1].win_rate == D("50.0000")


@pytest.mark.parametrize(
    ("value", "size", "expected"),
    [("150", "10000", D("1.5000")), ("1", "3", D("33.3333")), ("5", None, None), ("5", "0", None)],
)
def test_pct_of_account_size(value: str, size: str | None, expected: Decimal | None) -> None:
    assert pct(D(value), None if size is None else D(size)) == expected

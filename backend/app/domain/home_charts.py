"""Home charts (M8-14; docs/api.md "M8-14"): pure, Decimal only.

- Equity curve and P&L by day: every closed trade of the range, excluded ones included
  (account money, M8-01), Brussels dates.
- Rolling win rate / average R: strategy trades only (M8-01 exclusions out), the last
  ``window`` of them at each trade, with the digest's outcome rule (breakeven by |R|).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.domain import digest_metrics as dm

ROLLING_WINDOW = 20
_STEP = Decimal("0.0001")
_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class ChartTrade:
    id: int
    account_id: int
    close_time: datetime  # aware UTC
    net_pnl: Decimal
    r_multiple: Decimal | None
    excluded: bool  # M8-01: out of strategy statistics


@dataclass(frozen=True)
class EquityPoint:
    time: datetime
    cum_pnl: Decimal


@dataclass(frozen=True)
class DayPnl:
    day: date  # Brussels
    net_pnl: Decimal
    trades: int


@dataclass(frozen=True)
class RollingPoint:
    trade_id: int
    time: datetime
    n: int  # trades in the window (fewer than the window at the start)
    win_rate: Decimal  # percent, 4 dp
    avg_r: Decimal | None  # over the window's trades that have R


def _q(value: Decimal) -> Decimal:
    return value.quantize(_STEP, rounding=ROUND_HALF_UP)


def pct(value: Decimal, size: Decimal | None) -> Decimal | None:
    """``value`` as a percent of the account size (4 dp); None without a size."""
    if size is None or size <= 0:
        return None
    return _q(value / size * _HUNDRED)


def _ordered(trades: Iterable[ChartTrade]) -> list[ChartTrade]:
    return sorted(trades, key=lambda t: (t.close_time, t.id))


def equity(trades: Iterable[ChartTrade], start: date) -> list[EquityPoint]:
    """Running P&L from 0 at Brussels midnight of ``start`` through every trade."""
    points = [EquityPoint(time=dm._origin(start), cum_pnl=_ZERO)]
    running = _ZERO
    for t in _ordered(trades):
        running += t.net_pnl
        points.append(EquityPoint(time=t.close_time, cum_pnl=running))
    return points


def daily_pnl(trades: Iterable[ChartTrade]) -> list[DayPnl]:
    """Net P&L per Brussels close date (days with trades only)."""
    days: dict[date, list[Decimal]] = {}
    for t in _ordered(trades):
        days.setdefault(dm.brussels_date(t.close_time), []).append(t.net_pnl)
    return [DayPnl(day=d, net_pnl=sum(v, _ZERO), trades=len(v)) for d, v in sorted(days.items())]


def _digest_trade(t: ChartTrade, breakeven_r: Decimal) -> dm.DigestTrade:
    return dm.DigestTrade(
        id=t.id,
        account_id=t.account_id,
        symbol="",
        close_time=t.close_time,
        net_pnl=t.net_pnl,
        r_multiple=t.r_multiple,
        breakeven_r_threshold=breakeven_r,
    )


def rolling(
    trades: Iterable[ChartTrade], *, window: int = ROLLING_WINDOW, breakeven_r: Decimal
) -> list[RollingPoint]:
    """One point per strategy trade: win rate and average R of the last ``window`` trades."""
    strategy = [t for t in _ordered(trades) if not t.excluded]
    points: list[RollingPoint] = []
    for i, t in enumerate(strategy):
        last: Sequence[ChartTrade] = strategy[max(0, i + 1 - window) : i + 1]
        wins = sum(1 for x in last if dm.outcome(_digest_trade(x, breakeven_r)) == "win")
        rs = [x.r_multiple for x in last if x.r_multiple is not None]
        points.append(
            RollingPoint(
                trade_id=t.id,
                time=t.close_time,
                n=len(last),
                win_rate=_q(Decimal(wins) / len(last) * _HUNDRED),
                avg_r=_q(sum(rs, _ZERO) / len(rs)) if rs else None,
            )
        )
    return points

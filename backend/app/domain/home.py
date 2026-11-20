"""«Головна» KPIs, limits and live open-position R (M8-10b; docs/api.md "M8-10b"). Pure, Decimal.

Rounding is left to the API edge (4 dp percent/R, 2 dp money). The rolling win rate /
average R and the equity curve are `app.domain.home_charts` (M8-14), reused as is.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.domain import home_charts as hc
from app.domain.digest_metrics import _origin
from app.models.enums import Direction

ZERO = Decimal(0)
HUNDRED = Decimal(100)
KPI_POINTS = hc.ROLLING_WINDOW  # last 20 rolling points on the KPI sparklines
# Rolling points are computed from the last 2 x window - 1 strategy trades: the oldest of
# the last ``KPI_POINTS`` points still has a full window.
ROLLING_TRADES = KPI_POINTS + hc.ROLLING_WINDOW - 1


@dataclass(frozen=True)
class DrawdownPoint:
    time: datetime
    pct: Decimal  # <= 0, percent of the account size


@dataclass(frozen=True)
class OpenTotals:
    pnl: Decimal | None
    risk_pct: Decimal | None
    price_time: datetime | None


def month_start(day: date) -> date:
    return day.replace(day=1)


def drawdown(trades: Iterable[hc.ChartTrade], start: date, size: Decimal) -> list[DrawdownPoint]:
    """Running P&L from 0 at Brussels midnight of ``start``; each point is (running - peak
    so far) / size x 100. The peak starts at 0, so the curve is never above 0."""
    points = [DrawdownPoint(_origin(start), ZERO)]
    running = peak = ZERO
    for t in sorted(trades, key=lambda t: (t.close_time, t.id)):
        running += t.net_pnl
        peak = max(peak, running)
        points.append(DrawdownPoint(t.close_time, (running - peak) / size * HUNDRED))
    return points


def _sign(direction: str) -> Decimal:
    return Decimal(1) if direction == Direction.BUY.value else Decimal(-1)


def _sl_distance(direction: str, entry: Decimal, initial_sl: Decimal | None) -> Decimal | None:
    """Entry-to-SL distance in price, > 0 for a stop on the losing side; else None."""
    if initial_sl is None:
        return None
    distance = (entry - initial_sl) * _sign(direction)
    return distance if distance > 0 else None


def r_now(
    direction: str, entry: Decimal, initial_sl: Decimal | None, price: Decimal | None
) -> Decimal | None:
    """Signed price move from entry in units of the initial SL distance (-1 at the SL)."""
    distance = _sl_distance(direction, entry, initial_sl)
    if distance is None or price is None:
        return None
    return (price - entry) * _sign(direction) / distance


def tp_r(
    direction: str, entry: Decimal, initial_sl: Decimal | None, tp: Decimal | None
) -> Decimal | None:
    """TP distance / initial SL distance (signed: a TP on the losing side is negative)."""
    distance = _sl_distance(direction, entry, initial_sl)
    if distance is None or tp is None or tp <= 0:
        return None
    return (tp - entry) * _sign(direction) / distance


def with_floating(closed_pnl: Decimal, floating: Decimal, size: Decimal | None) -> Decimal | None:
    """(closed net P&L of the period + floating P&L) / size x 100; None without a size."""
    if size is None or not size.is_finite() or size <= 0:
        return None
    return (closed_pnl + floating) / size * HUNDRED


def to_daily_stop(day_pct: Decimal | None, loss_pct: Decimal | None) -> Decimal | None:
    """Room to the daily stop: day pct - daily_stop_loss_pct (+2.1 - (-3.0) = 5.1)."""
    if day_pct is None or loss_pct is None:
        return None
    return day_pct - loss_pct


def closest_to_daily_stop[T](items: Sequence[T], room: Callable[[T], Decimal | None]) -> T | None:
    """The item with the lowest room to its daily stop; items without a value come last and
    ties keep the input order (the caller passes accounts by id)."""
    if not items:
        return None
    known = [item for item in items if room(item) is not None]
    if not known:
        return items[0]
    return min(known, key=lambda item: room(item) or ZERO)


def open_totals(
    pnls: Sequence[Decimal | None],
    risks: Sequence[Decimal | None],
    times: Sequence[datetime | None],
) -> OpenTotals:
    """Sum of the open positions; a total is None when any part is unknown (a partial sum
    would understate P&L or risk). ``price_time`` = the oldest live price time."""
    known_times = [t for t in times if t is not None]
    return OpenTotals(
        pnl=None if None in pnls else sum((p for p in pnls if p is not None), ZERO),
        risk_pct=None if None in risks else sum((r for r in risks if r is not None), ZERO),
        price_time=min(known_times) if known_times and len(known_times) == len(times) else None,
    )


# --- max loss (FundedNext static floor; follow-up 2026-11-20) --------------------------------

MAX_LOSS_POINTS = 60  # sparkline cap; the final «now» point is always kept


@dataclass(frozen=True)
class MaxLossPoint:
    time: datetime
    pct: Decimal  # distance to the floor, percent of the account size (0 = failed)


@dataclass(frozen=True)
class FirmLimits:
    """Month / max-loss limits of one account, signed like rules.yaml (loss < 0)."""

    max_loss_pct: Decimal | None
    profit_target_pct: Decimal | None


def _set(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def firm_limits(
    account_max_drawdown: Decimal | None,
    account_profit_target: Decimal | None,
    config_max_loss: Decimal | None,
    config_profit_target: Decimal | None,
) -> FirmLimits:
    """The account's own firm rules (Settings, positive percents) when it has any of them,
    else the rules.yaml `account_limits` fallback. A funded account without a profit target
    has none (the fallback target is not mixed in)."""
    if _set(account_max_drawdown) or _set(account_profit_target):
        return FirmLimits(
            -account_max_drawdown if account_max_drawdown and _set(account_max_drawdown) else None,
            account_profit_target if _set(account_profit_target) else None,
        )
    return FirmLimits(config_max_loss, config_profit_target)


def usable_size(size: Decimal | None) -> Decimal | None:
    """The account size when finite and > 0, else None."""
    if size is None or not size.is_finite() or size <= 0:
        return None
    return size


def max_loss_floor(size: Decimal, limit_pct: Decimal) -> Decimal:
    """Equity at which the account fails: size x (1 + limit_pct / 100), 10 000 at -10 -> 9 000."""
    return size * (1 + limit_pct / HUNDRED)


def max_loss_distance(equity: Decimal, size: Decimal, limit_pct: Decimal) -> Decimal:
    """(equity - floor) / size x 100: 10 056.25 on 10 000 at -10 -> 10.5625."""
    return (equity - max_loss_floor(size, limit_pct)) / size * HUNDRED


def max_loss_series(
    size: Decimal,
    limit_pct: Decimal,
    start: datetime,
    closed: Iterable[tuple[datetime, int, Decimal]],
    now: datetime,
    equity_now: Decimal,
) -> list[MaxLossPoint]:
    """Start point (balance = size, distance -limit_pct), one point per closed trade
    ``(close_time, id, net_pnl)`` on the running balance size + cumulative P&L, then ``now``
    at ``equity_now``. The last ``MAX_LOSS_POINTS`` points, the final one included."""
    points = [MaxLossPoint(start, max_loss_distance(size, size, limit_pct))]
    running = size
    for close_time, _, pnl in sorted(closed, key=lambda row: (row[0], row[1])):
        running += pnl
        points.append(MaxLossPoint(close_time, max_loss_distance(running, size, limit_pct)))
    points.append(MaxLossPoint(now, max_loss_distance(equity_now, size, limit_pct)))
    return points[-MAX_LOSS_POINTS:]

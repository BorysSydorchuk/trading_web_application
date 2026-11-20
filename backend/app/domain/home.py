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

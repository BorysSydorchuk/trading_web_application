"""Period P&L and stop-limit state (PRD 6.9, 6.10; docs/api.md "Dashboard API"). Pure: no DB.

Shared by the rules engine (daily/weekly stop before an entry) and the dashboard (today /
this week). Periods are the local day and the Mon-Sun local week of the config timezone
(Europe/Brussels), keyed by close time. The running P&L is replayed in (close_time, key)
order; low/high are the sticky extremes of that running total (both start at 0). Percents
are of the account size (accounts.reference_balance), never of a balance.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from app.domain.sessions import to_local

HUNDRED = Decimal(100)
ZERO = Decimal(0)

LimitState = Literal["ok", "stop_loss", "stop_profit"]


class ClosedTrade(Protocol):
    """What the replay needs from a trade; open trades have ``close_time`` None."""

    @property
    def key(self) -> int: ...

    @property
    def close_time(self) -> datetime | None: ...

    @property
    def net_pnl(self) -> Decimal | None: ...


@dataclass(frozen=True)
class PeriodExtremes:
    pnl: Decimal
    pct: Decimal
    low_pnl: Decimal
    low_pct: Decimal
    high_pnl: Decimal
    high_pct: Decimal


def local_day(dt: datetime, tz: str) -> date:
    """Calendar day of aware ``dt`` in ``tz``."""
    return to_local(dt, tz).date()


def week_start(dt: datetime, tz: str) -> date:
    """Monday of the local Mon-Sun week of aware ``dt`` in ``tz``."""
    day = local_day(dt, tz)
    return day - timedelta(days=day.weekday())


def period_extremes(
    closed_trades: Iterable[ClosedTrade],
    period_key_fn: Callable[[datetime], date],
    start_key: date,
    size: Decimal | None,
    before: datetime | None = None,
) -> PeriodExtremes | None:
    """Running total and sticky low/high of the trades closed in the period ``start_key``
    (and strictly before ``before`` when given). ``None`` without a usable size."""
    if size is None or not size.is_finite() or size <= 0:
        return None
    counted: list[tuple[datetime, int, Decimal]] = []
    for t in closed_trades:
        close, pnl = t.close_time, t.net_pnl
        if close is None or pnl is None:
            continue
        if before is not None and close >= before:
            continue
        if period_key_fn(close) == start_key:
            counted.append((close, t.key, pnl))
    counted.sort(key=lambda row: (row[0], row[1]))
    running = low = high = ZERO
    for _, _, pnl in counted:
        running += pnl
        low = min(low, running)
        high = max(high, running)
    return PeriodExtremes(
        pnl=running,
        pct=running / size * HUNDRED,
        low_pnl=low,
        low_pct=low / size * HUNDRED,
        high_pnl=high,
        high_pct=high / size * HUNDRED,
    )


def limit_state(
    extremes: PeriodExtremes | None,
    loss_pct: Decimal | None,
    profit_pct: Decimal | None,
) -> LimitState:
    """``stop_loss`` once the sticky low reached ``loss_pct`` (wins over profit),
    ``stop_profit`` once the sticky high reached ``profit_pct``; a ``None`` limit is off."""
    if extremes is None:
        return "ok"
    if loss_pct is not None and extremes.low_pct <= loss_pct:
        return "stop_loss"
    if profit_pct is not None and extremes.high_pct >= profit_pct:
        return "stop_profit"
    return "ok"

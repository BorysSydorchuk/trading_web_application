"""Equal-weighted percent of several accounts («Головна» %-only, owner 2026-11-27). Pure, Decimal.

Accounts of different sizes (10K and 100K) each count the same: the combined percent is the
average of the per-account percents, not the sum of money over the sum of sizes. With one
account it is that account's percent (identical to `home_charts.pct`).

    combined = (1 / N) * sum over accounts a of (pnl_a / size_a * 100)
             = (1 / N) * sum over trades t of (pnl_t / size_of(t) * 100)

so a running curve adds each trade's share ``pnl_t / size_of(t) * 100 / N``. ``N`` is the
number of counted accounts (the selected one, or those with a trade in the period, as
`period_base` counts them). Any counted account without a usable size -> no percent (None),
never a partial average. Values are rounded to 4 dp only at the end.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.domain import digest_metrics as dm
from app.domain.home_charts import ChartTrade

_STEP = Decimal("0.0001")
_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_STEP, rounding=ROUND_HALF_UP)


def _usable(size: Decimal | None) -> bool:
    return size is not None and size.is_finite() and size > 0


@dataclass(frozen=True)
class Basis:
    """The counted accounts and their sizes (all usable)."""

    sizes: Mapping[int, Decimal]

    def share(self, account_id: int, pnl: Decimal) -> Decimal:
        """One trade's (or one account's) part of the combined percent, unrounded."""
        return pnl / self.sizes[account_id] * _HUNDRED / len(self.sizes)


def basis(sizes: Mapping[int, Decimal | None], counted: Collection[int]) -> Basis | None:
    """None when a counted account has no usable size; no counted account -> empty basis."""
    chosen: dict[int, Decimal] = {}
    for account_id in counted:
        size = sizes.get(account_id)
        if size is None or not _usable(size):
            return None
        chosen[account_id] = size
    return Basis(chosen)


def _ordered(trades: Iterable[ChartTrade]) -> list[ChartTrade]:
    return sorted(trades, key=lambda t: (t.close_time, t.id))


def cumulative(trades: Iterable[ChartTrade], base: Basis | None) -> list[Decimal | None]:
    """Running combined percent: 0 first, then one value per trade (``home_charts.equity``
    order). All None without a basis."""
    ordered = _ordered(trades)
    if base is None:
        return [None] * (len(ordered) + 1)
    running = _ZERO
    out: list[Decimal | None] = [_ZERO]
    for t in ordered:
        running += base.share(t.account_id, t.net_pnl)
        out.append(_q(running))
    return out


def by_day(trades: Iterable[ChartTrade], base: Basis | None) -> dict[date, Decimal]:
    """Combined percent per Brussels close date; empty without a basis."""
    if base is None:
        return {}
    days: dict[date, Decimal] = {}
    for t in _ordered(trades):
        day = dm.brussels_date(t.close_time)
        days[day] = days.get(day, _ZERO) + base.share(t.account_id, t.net_pnl)
    return {day: _q(value) for day, value in days.items()}


def average(
    pnl_by_account: Mapping[int, Decimal | None], sizes: Mapping[int, Decimal | None]
) -> Decimal | None:
    """Mean of the per-account percents (open positions); None when any value is unknown."""
    if not pnl_by_account or any(v is None for v in pnl_by_account.values()):
        return None
    base = basis(sizes, list(pnl_by_account))
    if base is None:
        return None
    return _q(sum((base.share(a, v) for a, v in pnl_by_account.items() if v is not None), _ZERO))


def total_r(trades: Iterable[ChartTrade]) -> Decimal | None:
    """Plain sum of R of the trades that have one; None when none has."""
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    return _q(sum(rs, _ZERO)) if rs else None

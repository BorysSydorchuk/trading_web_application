"""Home charts data (M8-14; docs/api.md "M8-14").

Closed trades of non-archived accounts (one account or all). The range is Brussels dates
``from``..``to`` inclusive. Equity and daily P&L: every trade of the range (account money,
excluded trades included). Rolling win rate / average R: computed over all strategy trades,
so the window reaches back before the range start, then shown for the range only.
Percent of account size: `app.domain.period_base` (one account's size, or the sum of the
sizes of the accounts with a trade in the range, excluded trades included; the digest's rule).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files import ConfigError, get_rules
from app.domain import home_charts as hc
from app.domain.period_base import period_base
from app.domain.sessions import DEFAULT_TZ
from app.errors import ApiError, config_error
from app.models import Account, Trade
from app.models.enums import AccountStatus
from app.schemas import home_charts as schemas

# Custom dates outside this window are rejected (422) instead of overflowing datetime.
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2100, 12, 31)


def _midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=ZoneInfo(DEFAULT_TZ)).astimezone(UTC)


def _accounts(db: Session, account_id: int | None) -> list[Account]:
    query = select(Account).where(Account.status != AccountStatus.ARCHIVED.value)
    if account_id is not None:
        query = query.where(Account.id == account_id)
    accounts = list(db.scalars(query))
    if account_id is not None and not accounts:
        raise ApiError(404, "not_found", "Account not found", {"id": account_id})
    return accounts


def _trades(db: Session, account_ids: list[int], until: datetime) -> list[hc.ChartTrade]:
    if not account_ids:
        return []
    rows = db.execute(
        select(
            Trade.id,
            Trade.account_id,
            Trade.close_time,
            Trade.net_pnl,
            Trade.r_multiple,
            Trade.excluded_from_stats,
        ).where(
            Trade.account_id.in_(account_ids),
            Trade.close_time.is_not(None),
            Trade.net_pnl.is_not(None),
            Trade.close_time < until,
        )
    ).all()
    trades: list[hc.ChartTrade] = []
    for trade_id, account, closed, pnl, r_multiple, excluded in rows:
        if closed is None or pnl is None:  # filtered in SQL; keeps the types honest
            continue
        trades.append(hc.ChartTrade(trade_id, account, closed, pnl, r_multiple, excluded))
    return trades


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        422, "validation_error", "Request validation failed", {"fields": {field: message}}
    )


def _check_range(start: date, end: date) -> None:
    for field, day in (("from", start), ("to", end)):
        if not MIN_DATE <= day <= MAX_DATE:
            raise _invalid(field, f"must be between {MIN_DATE} and {MAX_DATE}")
    if end < start:
        raise _invalid("to", "before from")


def build(db: Session, start: date, end: date, account_id: int | None) -> schemas.HomeCharts:
    _check_range(start, end)
    try:
        breakeven_r = get_rules().breakeven_r_threshold
    except ConfigError as exc:
        raise config_error(exc) from None
    accounts = _accounts(db, account_id)
    lo, hi = _midnight_utc(start), _midnight_utc(end + timedelta(days=1))
    every = _trades(db, [a.id for a in accounts], hi)
    in_range = [t for t in every if t.close_time >= lo]
    active = {t.account_id for t in in_range}
    counted = [a for a in accounts if a.id in active or account_id is not None]
    currencies = {a.currency for a in counted}
    if len(currencies) > 1:  # same refusal as the digest: never add USD and EUR together
        raise ApiError(
            409,
            "mixed_currency",
            "The range has trades in more than one account currency",
            {"currencies": sorted(currencies)},
        )
    size = period_base({a.id: a.reference_balance for a in accounts}, active, account_id=account_id)
    rolling = [p for p in hc.rolling(every, breakeven_r=breakeven_r) if p.time >= lo]
    return schemas.HomeCharts(
        from_=start,
        to=end,
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
        account_size=size,
        trades=len(in_range),
        equity=[
            schemas.EquityPointOut(time=p.time, cum_pnl=p.cum_pnl, cum_pct=hc.pct(p.cum_pnl, size))
            for p in hc.equity(in_range, start)
        ],
        daily=[
            schemas.DayPnlOut(
                day=d.day, net_pnl=d.net_pnl, pct=hc.pct(d.net_pnl, size), trades=d.trades
            )
            for d in hc.daily_pnl(in_range)
        ],
        rolling=[
            schemas.RollingPointOut(time=p.time, n=p.n, win_rate=p.win_rate, avg_r=p.avg_r)
            for p in rolling
        ],
        rolling_window=hc.ROLLING_WINDOW,
    )

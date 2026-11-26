"""«До макс. збитку» KPI of `GET /api/home` (follow-up to M8-10b, 2026-11-20; docs/api.md).

FundedNext Stellar static max loss: the account fails when equity <= size x (1 +
account_limits.max_drawdown_pct / 100), size = accounts.reference_balance. The KPI is the
distance of equity now to that floor in percent of the size. Equity now: a fresh worker
balance sync (accounts.equity, ``mt5``), else the last synced balance (floating unknown,
``balance``), else size + every closed net P&L + the cash open trades already booked
(``trades``). Money side: M8-01 excluded trades count (real money).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config_files.firms import FirmsConfig
from app.config_files.rules import RulesConfig
from app.domain import home as dh
from app.models import Account, Trade
from app.schemas import home as schemas
from app.services import open_positions_snapshot as snapshot
from app.services.firm_day import account_firm_rules

ZERO = Decimal(0)


@dataclass(frozen=True)
class _History:
    closed: list[tuple[datetime, int, Decimal]]  # (close_time, id, net_pnl)
    first_open: datetime | None
    open_booked: Decimal  # net_pnl so far of the still-open trades (entry commission, ...)


def _histories(db: Session, account_ids: list[int]) -> dict[int, _History]:
    """Whole-history closed trades, first open time and open-trade cash per account."""
    closed: dict[int, list[tuple[datetime, int, Decimal]]] = {i: [] for i in account_ids}
    rows = db.execute(
        select(Trade.account_id, Trade.close_time, Trade.id, Trade.net_pnl).where(
            Trade.account_id.in_(account_ids),
            Trade.close_time.is_not(None),
            Trade.net_pnl.is_not(None),
        )
    ).all()
    for account, close_time, trade_id, pnl in rows:
        if close_time is not None and pnl is not None:
            closed[account].append((close_time, trade_id, pnl))
    firsts: dict[int, datetime] = {}
    for account, first in db.execute(
        select(Trade.account_id, func.min(Trade.open_time))
        .where(Trade.account_id.in_(account_ids))
        .group_by(Trade.account_id)
    ).all():
        firsts[account] = first
    booked: dict[int, Decimal] = {}
    for account, total in db.execute(
        select(Trade.account_id, func.sum(Trade.net_pnl))
        .where(Trade.account_id.in_(account_ids), Trade.close_time.is_(None))
        .group_by(Trade.account_id)
    ).all():
        booked[account] = total if total is not None else ZERO  # all open net_pnl NULL -> 0
    return {i: _History(closed[i], firsts.get(i), booked.get(i, ZERO)) for i in account_ids}


_EMPTY = _History([], None, ZERO)


def _equity_now(
    account: Account, size: Decimal, history: _History, now: datetime
) -> tuple[Decimal, schemas.EquitySource]:
    synced = account.balance_synced_at
    if synced is not None and now - synced <= snapshot.STALE_AFTER and account.equity is not None:
        return account.equity, "mt5"
    if account.balance is not None:
        return account.balance, "balance"
    closed = sum((pnl for _, _, pnl in history.closed), ZERO)
    return size + closed + history.open_booked, "trades"


def _account_kpi(
    account: Account, size: Decimal, limit: Decimal, history: _History, now: datetime
) -> schemas.MaxLossKpi:
    equity, source = _equity_now(account, size, history, now)
    points = dh.max_loss_series(size, limit, history.first_open or now, history.closed, now, equity)
    return schemas.MaxLossKpi(
        account_id=account.id,
        account_name=account.name,
        pct=dh.max_loss_distance(equity, size, limit),
        limit_pct=limit,
        equity=equity,
        equity_source=source,
        series=[schemas.PctPoint(time=p.time, pct=p.pct) for p in points],
    )


def account_firm_limits(account: Account, rules: RulesConfig, firms: FirmsConfig) -> dh.FirmLimits:
    """Effective firm limits: a firms.yaml entry (account Settings value first), else the
    per-account Settings values with the rules.yaml `account_limits` fallback."""
    max_loss_pct, target = account_firm_rules(account, rules, firms).limits()
    return dh.FirmLimits(max_loss_pct, target)


def account_equity(db: Session, account: Account, size: Decimal, now: datetime) -> Decimal:
    """Equity now of one account (fresh sync, else balance, else the trades)."""
    return _equity_now(account, size, _histories(db, [account.id])[account.id], now)[0]


def accounts_equity(
    db: Session, pairs: Sequence[tuple[Account, Decimal]], now: datetime
) -> dict[int, Decimal]:
    """Equity now per account id (fresh sync, else balance, else the trades). The trade
    histories are read once, only for the accounts that have neither."""
    needs = [
        account.id
        for account, _ in pairs
        if account.balance is None and _equity_now(account, ZERO, _EMPTY, now)[1] == "trades"
    ]
    histories = _histories(db, needs) if needs else {}
    return {
        account.id: _equity_now(account, size, histories.get(account.id, _EMPTY), now)[0]
        for account, size in pairs
    }


def max_loss(
    db: Session,
    accounts: Sequence[Account],
    rules: RulesConfig,
    firms: FirmsConfig,
    now: datetime,
) -> schemas.MaxLossKpi | None:
    """One account: that account; all accounts: the one closest to its floor (lowest pct,
    ties -> lowest id). Limit per account (Settings firm rules, else rules.yaml account_limits);
    None when no account has a size and a limit."""
    usable = [
        (a, s, limit)
        for a in accounts
        if (s := dh.usable_size(a.reference_balance)) is not None
        and (limit := account_firm_limits(a, rules, firms).max_loss_pct) is not None
    ]
    if not usable:
        return None
    histories = _histories(db, [a.id for a, _, _ in usable])
    items = [_account_kpi(a, s, limit, histories[a.id], now) for a, s, limit in usable]
    return dh.closest_to_daily_stop(items, lambda item: item.pct)

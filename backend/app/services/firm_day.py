"""Firm rules of an account and its firm day (docs/api.md "Firm rules from config:
KeyFunding"): the DB side of `app.domain.firm_rules`.

Also the floating-P&L helpers shared by Home and the dashboard: a worker balance sync is
fresh when it is not older than the snapshot staleness limit.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files.firms import FirmsConfig
from app.config_files.rules import RulesConfig
from app.domain import firm_rules as fr
from app.domain import home as dh
from app.models import Account, Trade, TradeExitDeal
from app.services import open_positions_snapshot as snapshot

ZERO = Decimal(0)


def balance_fresh(account: Account, now: datetime) -> bool:
    synced = account.balance_synced_at
    return synced is not None and now - synced <= snapshot.STALE_AFTER


def floating(account: Account, has_open: bool, now: datetime) -> tuple[Decimal | None, bool]:
    """(floating P&L, included). Fresh worker sync (<= the snapshot staleness limit):
    equity - balance. Stale / unknown: 0 when the account has no open trade (closed P&L is
    then the whole result), else None and not included."""
    equity, balance = account.equity, account.balance
    if balance_fresh(account, now) and equity is not None and balance is not None:
        return equity - balance, True
    if not has_open:
        return Decimal(0), True
    return None, False


def account_firm_rules(
    account: Account, rules: RulesConfig | None, firms: FirmsConfig
) -> fr.FirmRules:
    """Effective rules of ``account``; ``rules`` supplies the rules.yaml `account_limits`
    fallback (None = no fallback)."""
    cfg = rules.account_limits if rules is not None else None
    return fr.effective_rules(
        account_firm=account.firm,
        phase=account.phase,
        account_daily_loss_pct=account.daily_loss_pct,
        account_max_drawdown_pct=account.max_drawdown_pct,
        account_profit_target_pct=account.profit_target_pct,
        firms=firms,
        fallback_max_loss_pct=cfg.max_drawdown_pct if cfg is not None else None,
        fallback_profit_target_pct=cfg.profit_target_pct if cfg is not None else None,
    )


def _open_cash(db: Session, account_id: int) -> tuple[list[tuple[datetime, Decimal]], bool]:
    """Cash the account's open trades already booked, bucketed by the day it was booked:
    each exit deal (profit + commission + swap) at its own time, the rest of the trade's
    net P&L so far (entry commission, ...) at its open time. And whether any trade is open."""
    trades = db.execute(
        select(Trade.id, Trade.open_time, Trade.net_pnl).where(
            Trade.account_id == account_id, Trade.close_time.is_(None)
        )
    ).all()
    if not trades:
        return [], False
    deals = db.execute(
        select(
            TradeExitDeal.trade_id,
            TradeExitDeal.time,
            TradeExitDeal.profit + TradeExitDeal.commission + TradeExitDeal.swap,
        ).where(TradeExitDeal.trade_id.in_([t[0] for t in trades]))
    ).all()
    exited: dict[int, Decimal] = {}
    for trade_id, _, cash in deals:
        exited[trade_id] = exited.get(trade_id, ZERO) + cash
    rows = [
        (opened, (net or ZERO) - exited.get(trade_id, ZERO)) for trade_id, opened, net in trades
    ]
    rows.extend((at, cash) for _, at, cash in deals)
    return rows, True


def firm_day_of(
    db: Session, account: Account, effective: fr.FirmRules, now: datetime
) -> fr.FirmDay | None:
    """The firm day of an account with a firm entry and a usable size, else None."""
    day_rule = fr.day_rule(effective, account.server_offset_hours)
    size = dh.usable_size(account.reference_balance)
    if day_rule is None or size is None:
        return None
    reset = day_rule.reset_at(now)
    fresh = account.balance if balance_fresh(account, now) else None
    closed_query = select(Trade.close_time, Trade.net_pnl).where(
        Trade.account_id == account.id,
        Trade.close_time.is_not(None),
        Trade.net_pnl.is_not(None),
    )
    if fresh is not None:  # the start balance only needs the trades closed since the reset
        closed_query = closed_query.where(Trade.close_time >= reset)
    closed = [(t, p) for t, p in db.execute(closed_query) if t is not None and p is not None]
    booked, has_open = _open_cash(db, account.id)
    return fr.firm_day(
        size=size,
        daily_loss_pct=day_rule.daily_loss_pct,
        reset_at=reset,
        closed=closed,
        open_booked=booked,
        fresh_balance=fresh,
        floating=floating(account, has_open, now)[0],
        to_verify=effective.to_verify,
    )

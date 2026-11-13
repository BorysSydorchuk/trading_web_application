"""Dashboard service (docs/api.md "Dashboard API (PRD 6.10)", M6-03 details).

Today (Brussels day) and this week (Mon-Sun Brussels) P&L per active account as % of the
account size (accounts.reference_balance), with the sticky low/high replay shared with the
rules engine (`app.domain.period_pnl`) and the stop limits of config/rules.yaml.
Fixed number of queries whatever the number of accounts: accounts, closed trades of the
week, open positions, inbox counts.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files import ConfigError, get_rules
from app.config_files.rules import DecimalRule, RulesConfig
from app.domain.period_pnl import (
    PeriodExtremes,
    limit_state,
    local_day,
    period_extremes,
    week_start,
)
from app.errors import config_error
from app.models import Account, Trade
from app.models.enums import AccountStatus
from app.schemas import dashboard as schemas
from app.services.inbox import count_inbox

ZERO = Decimal(0)
ZERO_EXTREMES = PeriodExtremes(ZERO, ZERO, ZERO, ZERO, ZERO, ZERO)
# The DB window is a superset of the local week; the exact period filter is in the domain.
WINDOW_MARGIN = timedelta(days=1)


@dataclass(frozen=True)
class _Closed:
    key: int
    close_time: datetime | None
    net_pnl: Decimal | None


def _limit(rule: DecimalRule) -> Decimal | None:
    return rule.value if rule.enabled else None


def _limits(rules: RulesConfig) -> schemas.Limits:
    cfg = rules.rules
    return schemas.Limits(
        daily_loss_pct=_limit(cfg.daily_stop_loss_pct),
        daily_profit_pct=_limit(cfg.daily_stop_profit_pct),
        weekly_loss_pct=_limit(cfg.weekly_stop_loss_pct),
        weekly_profit_pct=_limit(cfg.weekly_stop_profit_pct),
    )


def _block(extremes: PeriodExtremes | None) -> schemas.PeriodBlock:
    ex = extremes or ZERO_EXTREMES
    return schemas.PeriodBlock(
        pnl=ex.pnl,
        pct=ex.pct,
        low_pnl=ex.low_pnl,
        low_pct=ex.low_pct,
        high_pnl=ex.high_pnl,
        high_pct=ex.high_pct,
    )


def _week_window(monday: date, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    start = datetime.combine(monday, time(0), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(monday + timedelta(days=7), time(0), tzinfo=zone).astimezone(UTC)
    return start - WINDOW_MARGIN, end + WINDOW_MARGIN


def _closed_by_account(
    db: Session, account_ids: Sequence[int], monday: date, tz: str
) -> dict[int, list[_Closed]]:
    start, end = _week_window(monday, tz)
    rows = db.execute(
        select(Trade.id, Trade.account_id, Trade.close_time, Trade.net_pnl).where(
            Trade.account_id.in_(account_ids),
            Trade.close_time.is_not(None),
            Trade.close_time >= start,
            Trade.close_time < end,
        )
    )
    out: dict[int, list[_Closed]] = defaultdict(list)
    for trade_id, account_id, close_time, net_pnl in rows:
        out[account_id].append(_Closed(trade_id, close_time, net_pnl))
    return out


def _account_item(
    account: Account,
    trades: list[_Closed],
    tz: str,
    now: datetime,
    limits: schemas.Limits,
) -> schemas.DashboardAccount:
    def day_key(dt: datetime) -> date:
        return local_day(dt, tz)

    def week_key(dt: datetime) -> date:
        return week_start(dt, tz)

    size = account.reference_balance
    today = period_extremes(trades, day_key, day_key(now), size)
    week = period_extremes(trades, week_key, week_key(now), size)
    return schemas.DashboardAccount(
        id=account.id,
        name=account.name,
        currency=account.currency,
        account_size=size,
        today=_block(today),
        week=_block(week),
        limits=limits,
        today_state=limit_state(today, limits.daily_loss_pct, limits.daily_profit_pct),
        week_state=limit_state(week, limits.weekly_loss_pct, limits.weekly_profit_pct),
    )


def _open_positions(db: Session) -> list[schemas.OpenPosition]:
    rows = db.execute(
        select(Trade, Account.name)
        .join(Account, Account.id == Trade.account_id)
        .where(Account.status == AccountStatus.ACTIVE.value, Trade.close_time.is_(None))
        .order_by(Trade.open_time, Trade.id)
    )
    return [
        schemas.OpenPosition(
            trade_id=trade.id,
            account_name=account_name,
            symbol=trade.symbol,
            direction=trade.direction,
            volume=trade.volume,
            entry_price=trade.entry_price,
            open_time=trade.open_time,
            initial_sl=trade.initial_sl,
            risk_amount=trade.risk_amount,
            risk_pct=trade.risk_pct,
        )
        for trade, account_name in rows
    ]


def build_dashboard(db: Session, now: datetime) -> schemas.Dashboard:
    """The home-page payload at ``now`` (aware UTC). Broken rules.yaml -> 500 config_error."""
    try:
        rules = get_rules()
    except ConfigError as exc:
        raise config_error(exc) from exc
    tz = rules.timezone
    accounts = db.scalars(
        select(Account).where(Account.status == AccountStatus.ACTIVE.value).order_by(Account.id)
    ).all()
    limits = _limits(rules)
    closed = _closed_by_account(db, [a.id for a in accounts], week_start(now, tz), tz)
    items = [_account_item(a, closed.get(a.id, []), tz, now, limits) for a in accounts]
    return schemas.Dashboard(
        now=now,
        accounts=items,
        stop=schemas.StopFlags(
            today=any(a.today_state != "ok" for a in items),
            week=any(a.week_state != "ok" for a in items),
        ),
        open_positions=_open_positions(db),
        inbox=count_inbox(db),
    )

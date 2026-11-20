"""`GET /api/home` (M8-10b; docs/api.md "M8-10b - «Головна» rebuild").

Accounts: one (``account_id``, any non-archived account, else 404) or every active account.
Money side (today P&L, limits, drawdown, open P&L) includes M8-01 excluded trades; the win
rate / average R KPIs use strategy trades only (M8-14 rolling rule, reused). Percents are of
the account size (one account) or of the combined size of the accounts with a trade in the
period (all accounts, the digest rule; every selected account when none traded). Open
positions get live values from the worker's snapshot file (never fails the endpoint).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config_files import ConfigError, get_rules
from app.config_files.rules import WEEKDAYS as RULE_WEEKDAYS
from app.config_files.rules import DecimalRule, RulesConfig
from app.domain import home as dh
from app.domain import home_charts as hc
from app.domain.period_pnl import local_day, period_extremes, week_start
from app.domain.sessions import find_window, to_local
from app.errors import ApiError, config_error
from app.models import Account, BiasNote, Trade
from app.models.enums import AccountStatus, BiasKind
from app.schemas import home as schemas
from app.services import open_positions_snapshot as snapshot
from app.services.home_charts import percent_base

OUTSIDE: Final = "outside"
WEEKDAYS = range(5)  # Monday..Friday, as the bias reminders (app.services.bias_status)


@dataclass(frozen=True)
class _Period:
    """Brussels dates of ``now``: today, Monday of the week, 1st of the month."""

    now: datetime
    tz: str
    today: date
    monday: date
    month: date

    def midnight(self, day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=ZoneInfo(self.tz)).astimezone(UTC)


@dataclass(frozen=True)
class _Keyed:
    """`app.domain.period_pnl.ClosedTrade` view of a chart trade."""

    key: int
    close_time: datetime | None
    net_pnl: Decimal | None


def _period(now: datetime, tz: str) -> _Period:
    today = local_day(now, tz)
    return _Period(now, tz, today, today - timedelta(days=today.weekday()), dh.month_start(today))


def _rules() -> RulesConfig:
    try:
        return get_rules()
    except ConfigError as exc:
        raise config_error(exc) from None


def _accounts(db: Session, account_id: int | None) -> list[Account]:
    query = select(Account).order_by(Account.id)
    if account_id is None:
        return list(db.scalars(query.where(Account.status == AccountStatus.ACTIVE.value)))
    found = list(
        db.scalars(
            query.where(Account.id == account_id, Account.status != AccountStatus.ARCHIVED.value)
        )
    )
    if not found:
        raise ApiError(404, "not_found", "Account not found", {"id": account_id})
    return found


def _closed_since(db: Session, account_ids: list[int], since: datetime) -> list[hc.ChartTrade]:
    """Closed trades from ``since`` on, excluded ones included (account money)."""
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
            Trade.close_time >= since,
            Trade.net_pnl.is_not(None),
        )
    ).all()
    return [
        hc.ChartTrade(trade_id, account, closed, pnl, r_multiple, excluded)
        for trade_id, account, closed, pnl, r_multiple, excluded in rows
        if closed is not None and pnl is not None
    ]


def _last_strategy_trades(db: Session, account_ids: list[int]) -> list[hc.ChartTrade]:
    """The last trades the rolling KPI points need (strategy trades only)."""
    if not account_ids:
        return []
    rows = db.execute(
        select(Trade.id, Trade.account_id, Trade.close_time, Trade.net_pnl, Trade.r_multiple)
        .where(
            Trade.account_id.in_(account_ids),
            Trade.close_time.is_not(None),
            Trade.net_pnl.is_not(None),
            Trade.excluded_from_stats.is_(False),
        )
        .order_by(Trade.close_time.desc(), Trade.id.desc())
        .limit(dh.ROLLING_TRADES)
    ).all()
    return [
        hc.ChartTrade(trade_id, account, closed, pnl, r_multiple, False)
        for trade_id, account, closed, pnl, r_multiple in rows
        if closed is not None and pnl is not None
    ]


def _open_trades(db: Session, account_ids: list[int]) -> list[tuple[Trade, Account]]:
    if not account_ids:
        return []
    rows = db.execute(
        select(Trade, Account)
        .join(Account, Account.id == Trade.account_id)
        .where(Trade.account_id.in_(account_ids), Trade.close_time.is_(None))
        .order_by(Trade.open_time, Trade.id)
    ).all()
    return [(trade, account) for trade, account in rows]


def _trades_this_week(db: Session, account_ids: list[int], period: _Period) -> dict[int, int]:
    """Trades opened this Brussels week per account, open and excluded ones included."""
    if not account_ids:
        return {}
    start = period.midnight(period.monday)
    end = period.midnight(period.monday + timedelta(days=7))
    rows = db.execute(
        select(Trade.account_id, func.count())
        .where(Trade.account_id.in_(account_ids), Trade.open_time >= start, Trade.open_time < end)
        .group_by(Trade.account_id)
    ).all()
    return {int(account): int(count) for account, count in rows}


# --- header ----------------------------------------------------------------------------------


def _session(rules: RulesConfig, now: datetime) -> schemas.SessionNow:
    """Brussels now vs rules.yaml sessions; a non-trading day (sync.trading_days) is outside."""
    weekday = RULE_WEEKDAYS[to_local(now, rules.timezone).weekday()]
    window = find_window(now, rules.sessions, rules.timezone)
    if window is None or weekday not in rules.sync.trading_days:
        return schemas.SessionNow(key=OUTSIDE, entries_allowed=False)
    # Session names are validated against TradingSession by the rules loader.
    key = cast(schemas.SessionKey, window.name)
    return schemas.SessionNow(key=key, entries_allowed=window.entries_allowed)


def _bias_today(db: Session, period: _Period) -> schemas.BiasToday:
    notes = {
        note.kind: note
        for note in db.scalars(
            select(BiasNote)
            .where(
                BiasNote.period_date == period.today,
                BiasNote.kind.in_([BiasKind.PRE_LONDON.value, BiasKind.PRE_NY.value]),
            )
            .options(selectinload(BiasNote.entries))
        )
    }
    london = notes.get(BiasKind.PRE_LONDON.value)
    return schemas.BiasToday(
        pre_london=None
        if london is None
        else [schemas.BiasEntryOut(symbol=e.symbol, direction=e.direction) for e in london.entries],
        pre_ny_missing=period.today.weekday() in WEEKDAYS and BiasKind.PRE_NY.value not in notes,
    )


# --- limits ----------------------------------------------------------------------------------


def _rule(rule: DecimalRule) -> Decimal | None:
    return rule.value if rule.enabled else None


def _bar(
    trades: Sequence[_Keyed],
    key_fn: Callable[[datetime], date],
    start: date,
    size: Decimal,
    limits: tuple[Decimal | None, Decimal | None],
) -> schemas.LimitBar:
    extremes = period_extremes(trades, key_fn, start, size)
    loss, profit = limits
    pct = extremes.pct if extremes is not None else None
    return schemas.LimitBar(pct=pct, loss_pct=loss, profit_pct=profit)


def _period_keys(tz: str) -> tuple[Callable[[datetime], date], ...]:
    """Brussels day, Monday of the week and 1st of the month of a close time."""

    def day(dt: datetime) -> date:
        return local_day(dt, tz)

    def week(dt: datetime) -> date:
        return week_start(dt, tz)

    def month(dt: datetime) -> date:
        return dh.month_start(local_day(dt, tz))

    return day, week, month


def _account_limits(
    account: Account,
    trades: Sequence[hc.ChartTrade],
    trades_week: int,
    rules: RulesConfig,
    period: _Period,
) -> schemas.AccountLimitsOut:
    cfg, size = rules.rules, account.reference_balance
    keyed = [_Keyed(t.id, t.close_time, t.net_pnl) for t in trades if t.account_id == account.id]
    day_key, week_key, month_key = _period_keys(period.tz)
    month_limits = rules.account_limits
    month_range = (
        (month_limits.max_drawdown_pct, month_limits.profit_target_pct)
        if month_limits is not None
        else (None, None)
    )
    day_range = (_rule(cfg.daily_stop_loss_pct), _rule(cfg.daily_stop_profit_pct))
    week_range = (_rule(cfg.weekly_stop_loss_pct), _rule(cfg.weekly_stop_profit_pct))
    day = _bar(keyed, day_key, period.today, size, day_range)
    max_trades = cfg.max_trades_per_week
    return schemas.AccountLimitsOut(
        account_id=account.id,
        account_name=account.name,
        currency=account.currency,
        day=day,
        week=_bar(keyed, week_key, period.monday, size, week_range),
        month=_bar(keyed, month_key, period.month, size, month_range),
        trades_week=trades_week,
        max_trades_week=max_trades.value if max_trades.enabled else None,
        to_daily_stop_pct=dh.to_daily_stop(day.pct, day.loss_pct),
    )


def _limits(
    db: Session,
    accounts: Sequence[Account],
    trades: Sequence[hc.ChartTrade],
    rules: RulesConfig,
    period: _Period,
) -> schemas.AccountLimitsOut | None:
    """One account: the selected one, or the one closest to its daily stop."""
    counts = _trades_this_week(db, [a.id for a in accounts], period)
    items = [_account_limits(a, trades, counts.get(a.id, 0), rules, period) for a in accounts]
    return dh.closest_to_daily_stop(items, lambda item: item.to_daily_stop_pct)


# --- KPIs ------------------------------------------------------------------------------------


def _size(
    accounts: Sequence[Account], trades: Sequence[hc.ChartTrade], one: bool
) -> Decimal | None:
    """One account: its size. All: the accounts with a trade (all selected when none)."""
    if one:
        return percent_base(accounts)
    traded = {t.account_id for t in trades}
    counted = [a for a in accounts if a.id in traded]
    return percent_base(counted or accounts)


def _today(
    accounts: Sequence[Account], trades: Sequence[hc.ChartTrade], period: _Period, one: bool
) -> schemas.TodayKpi:
    today = [t for t in trades if t.close_time >= period.midnight(period.today)]
    pnl = sum((t.net_pnl for t in today), Decimal(0))
    return schemas.TodayKpi(
        pnl=pnl,
        pct=hc.pct(pnl, _size(accounts, today, one)),
        trades=len(today),
        series=[
            schemas.CumPoint(time=p.time, cum_pnl=p.cum_pnl) for p in hc.equity(today, period.today)
        ],
    )


def _rolling(
    db: Session, account_ids: list[int], breakeven_r: Decimal
) -> tuple[schemas.RollingKpi, schemas.RollingKpi]:
    """Win rate and average R: the last 20 points of the M8-14 rolling chart."""
    trades = _last_strategy_trades(db, account_ids)
    points = hc.rolling(trades, breakeven_r=breakeven_r)[-dh.KPI_POINTS :]
    last = points[-1] if points else None
    window = hc.ROLLING_WINDOW
    win_rate = schemas.RollingKpi(
        value=last.win_rate if last is not None else None,
        n=last.n if last is not None else 0,
        window=window,
        series=[schemas.ValuePoint(time=p.time, value=p.win_rate) for p in points],
    )
    avg_r = schemas.RollingKpi(
        value=last.avg_r if last is not None else None,
        n=last.n if last is not None else 0,
        window=window,
        series=[
            schemas.ValuePoint(time=p.time, value=p.avg_r) for p in points if p.avg_r is not None
        ],
    )
    return win_rate, avg_r


def _drawdown(
    accounts: Sequence[Account],
    trades: Sequence[hc.ChartTrade],
    rules: RulesConfig,
    period: _Period,
    one: bool,
) -> schemas.DrawdownKpi:
    month = [t for t in trades if t.close_time >= period.midnight(period.month)]
    size = _size(accounts, month, one)
    limit = rules.account_limits.max_drawdown_pct if rules.account_limits is not None else None
    if size is None:
        return schemas.DrawdownKpi(pct=None, limit_pct=limit, series=[])
    points = dh.drawdown(month, period.month, size)
    return schemas.DrawdownKpi(
        pct=points[-1].pct,
        limit_pct=limit,
        series=[schemas.PctPoint(time=p.time, pct=p.pct) for p in points],
    )


def _kpis(
    db: Session,
    accounts: Sequence[Account],
    trades: Sequence[hc.ChartTrade],
    rules: RulesConfig,
    period: _Period,
    one: bool,
) -> schemas.Kpis:
    win_rate, avg_r = _rolling(db, [a.id for a in accounts], rules.breakeven_r_threshold)
    return schemas.Kpis(
        today=_today(accounts, trades, period, one),
        win_rate=win_rate,
        avg_r=avg_r,
        drawdown=_drawdown(accounts, trades, rules, period, one),
    )


# --- open positions --------------------------------------------------------------------------


def _position(
    trade: Trade, account: Account, live: snapshot.LiveValue | None, now: datetime
) -> schemas.OpenPositionOut:
    fresh = live if live is not None and snapshot.is_fresh(live, now) else None
    price = fresh.price_current if fresh is not None else None
    return schemas.OpenPositionOut(
        trade_id=trade.id,
        symbol=trade.symbol,
        direction=trade.direction,
        volume=trade.volume,
        account_id=account.id,
        account_name=account.name,
        open_time=trade.open_time,
        entry_price=trade.entry_price,
        initial_sl=trade.initial_sl,
        tp=trade.tp,
        current_price=price,
        price_time=live.time if live is not None else None,
        pnl=fresh.pnl if fresh is not None else None,
        r_now=dh.r_now(trade.direction, trade.entry_price, trade.initial_sl, price),
        tp_r=dh.tp_r(trade.direction, trade.entry_price, trade.initial_sl, trade.tp),
        mae_r=trade.mae_r,
        mfe_r=trade.mfe_r,
        risk_pct=trade.risk_pct,
        described=trade.described_at is not None,
    )


def _open_totals(positions: Sequence[schemas.OpenPositionOut]) -> schemas.OpenTotalsOut:
    totals = dh.open_totals(
        [p.pnl for p in positions],
        [p.risk_pct for p in positions],
        [p.price_time for p in positions],
    )
    return schemas.OpenTotalsOut(
        pnl=totals.pnl, risk_pct=totals.risk_pct, price_time=totals.price_time
    )


def _check_currency(
    accounts: Sequence[Account], trades: Sequence[hc.ChartTrade], open_ids: set[int]
) -> None:
    """Never add USD and EUR together (409 like the digest and the Home charts)."""
    used = {t.account_id for t in trades} | open_ids
    currencies = {a.currency for a in accounts if a.id in used}
    if len(currencies) > 1:
        raise ApiError(
            409,
            "mixed_currency",
            "The accounts have trades in more than one currency",
            {"currencies": sorted(currencies)},
        )


# --- endpoint --------------------------------------------------------------------------------


def build_home(db: Session, now: datetime, account_id: int | None, data_dir: Path) -> schemas.Home:
    """The «Головна» payload at ``now`` (aware UTC). Broken rules.yaml -> 500 config_error."""
    rules = _rules()
    period = _period(now, rules.timezone)
    accounts = _accounts(db, account_id)
    ids = [a.id for a in accounts]
    since = min(period.midnight(period.month), period.midnight(period.monday))
    trades = _closed_since(db, ids, since)
    opened = _open_trades(db, ids)
    _check_currency(accounts, trades, {a.id for _, a in opened})
    live = snapshot.read_snapshot(snapshot.snapshot_path(data_dir)) if opened else {}
    positions = [_position(t, a, live.get((a.id, t.position_id)), now) for t, a in opened]
    one = account_id is not None
    return schemas.Home(
        now=now,
        timezone=rules.timezone,
        session=_session(rules, now),
        bias_today=_bias_today(db, period),
        limits=_limits(db, accounts, trades, rules, period),
        kpis=_kpis(db, accounts, trades, rules, period, one),
        open_positions=positions,
        open_totals=_open_totals(positions),
    )

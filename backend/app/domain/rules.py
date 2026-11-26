"""Rules engine v1 (PRD 6.9; DECISIONS 2026-11-01). Pure: no DB, config passed in.

``evaluate`` checks one trade against the enabled rules in ``RulesConfig.rules``, using the
other trades (``context``) for day/week/idea rules. Missing inputs never produce a violation.

Conventions (local = ``RulesConfig.timezone``, Europe/Brussels):
- Daily/weekly stop: P&L of the same account's trades closed strictly before this trade's
  open, whose close falls on the same local day / Mon-Sun week as this trade's open, as %
  of the account size (``account_size`` = accounts.reference_balance, M5-10; never a
  balance). No usable size (None or <= 0) -> no stop violation. Sticky: the running P&L is
  replayed in close order and a limit crossed at any point flags every later entry of the
  period, even if P&L recovered.
- firm_daily_loss: same replay over the firm day (`app.domain.firm_rules`: reset time and
  zone of the firm, not the Brussels day), only when ``RuleTradeInput.firm`` is set.
- max_risk_pct: compares ``risk_pct`` (already % of the account size).
- entry_session: flagged for ``outside`` or a configured window without entries; a session
  name missing from the config is not a violation.
- max_trades_per_week: per account; trades ordered by (open_time, key); the N-th trade of a
  local Mon-Sun week is flagged when N > value.
- max_reentries_per_idea: idea = account + symbol + direction + session + local day; a
  re-entry (``is_reentry``) is flagged when the number of re-entries of its idea opened at or
  before it exceeds the value. A non-re-entry is never flagged by this rule.
- min_planned_rr: no TP (planned_rr None) is not a violation in v1.
- no_breakeven: needs a known initial SL that is not itself at entry (more than 1 tick away).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.config_files.rules import (
    DAILY_RISK_KEY,
    FIRM_DAILY_LOSS_KEY,
    WEEKLY_RISK_KEY,
    RulesConfig,
)
from app.domain.firm_rules import FirmDayRule
from app.domain.period_pnl import PeriodExtremes, local_day, period_extremes, week_start
from app.domain.sessions import OUTSIDE

PCT_Q = Decimal("0.01")
# Joins the loss and profit parts of one daily_risk / weekly_risk details text (M8-04).
RISK_DETAILS_SEPARATOR = "; "


@dataclass(frozen=True)
class RuleExitDeal:
    price: Decimal
    reason: str | None


@dataclass(frozen=True)
class RuleTradeInput:
    key: int  # trade id (or position id), unique within the context
    account_id: int
    symbol: str
    direction: str
    open_time: datetime  # aware UTC
    close_time: datetime | None
    session: str | None
    net_pnl: Decimal | None
    account_size: Decimal | None
    risk_pct: Decimal | None
    planned_rr: Decimal | None
    entry_price: Decimal | None
    last_sl: Decimal | None
    initial_sl: Decimal | None
    exit_deals: tuple[RuleExitDeal, ...] = field(default_factory=tuple)
    entry_model: str | None = None
    is_reentry: bool = False
    # Firm day rule of the account (only accounts with a firms.yaml entry), else None.
    firm: FirmDayRule | None = None


@dataclass(frozen=True)
class Violation:
    rule_key: str
    details: str


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(PCT_Q, rounding=ROUND_HALF_UP)}"


def _local_day(dt: datetime, tz: str) -> date:
    return local_day(dt, tz)


def _week_start(dt: datetime, tz: str) -> date:
    return week_start(dt, tz)


def _others(trade: RuleTradeInput, context: Iterable[RuleTradeInput]) -> list[RuleTradeInput]:
    return [t for t in context if t.key != trade.key and t.account_id == trade.account_id]


def _period_stop(
    trade: RuleTradeInput,
    others: list[RuleTradeInput],
    tz: str,
    weekly: bool,
) -> PeriodExtremes | None:
    """Lowest/highest running closed P&L of the period before entry (sticky stops).

    Trades closed in the period before this entry are replayed in (close_time, key) order;
    the running P&L is taken as % of the entering trade's account size.
    """
    period = week_start if weekly else local_day

    def key_fn(dt: datetime) -> date:
        return period(dt, tz)

    return period_extremes(
        others, key_fn, key_fn(trade.open_time), trade.account_size, before=trade.open_time
    )


def _period_risk(
    trade: RuleTradeInput, others: list[RuleTradeInput], rules: RulesConfig, weekly: bool
) -> Violation | None:
    """One `daily_risk` / `weekly_risk` violation (M8-04): the limits hit are named in the
    details by their rules.yaml key, loss part first, parts joined by "; "."""
    cfg = rules.rules
    if weekly:
        label, rule_key = "week", WEEKLY_RISK_KEY
        loss_key, profit_key = "weekly_stop_loss_pct", "weekly_stop_profit_pct"
        loss_rule, profit_rule = cfg.weekly_stop_loss_pct, cfg.weekly_stop_profit_pct
    else:
        label, rule_key = "day", DAILY_RISK_KEY
        loss_key, profit_key = "daily_stop_loss_pct", "daily_stop_profit_pct"
        loss_rule, profit_rule = cfg.daily_stop_loss_pct, cfg.daily_stop_profit_pct
    if not (loss_rule.enabled or profit_rule.enabled):
        return None
    stop = _period_stop(trade, others, rules.timezone, weekly)
    if stop is None:
        return None
    parts: list[str] = []
    if loss_rule.enabled and stop.low_pct <= loss_rule.value:
        parts.append(
            f"{loss_key}: {label} P&L reached {_fmt(stop.low_pct)}% ({_fmt(stop.low_pnl)}) "
            f"before entry <= limit {loss_rule.value}%"
        )
    if profit_rule.enabled and stop.high_pct >= profit_rule.value:
        parts.append(
            f"{profit_key}: {label} P&L reached {_fmt(stop.high_pct)}% ({_fmt(stop.high_pnl)}) "
            f"before entry >= limit {profit_rule.value}%"
        )
    return Violation(rule_key, RISK_DETAILS_SEPARATOR.join(parts)) if parts else None


def _firm_daily_loss(trade: RuleTradeInput, others: list[RuleTradeInput]) -> Violation | None:
    """`firm_daily_loss`: the realized P&L of the firm day (since the firm reset of this
    entry, closed strictly before it) reached -daily_loss_pct of the size; sticky like
    daily_risk. Only accounts with a firm day rule."""
    rule = trade.firm
    if rule is None:
        return None
    stop = period_extremes(
        others, rule.reset_at, rule.reset_at(trade.open_time), trade.account_size,
        before=trade.open_time,
    )  # fmt: skip
    if stop is None or stop.low_pct > -rule.daily_loss_pct:
        return None
    return Violation(
        FIRM_DAILY_LOSS_KEY,
        f"firm day P&L reached {_fmt(stop.low_pct)}% ({_fmt(stop.low_pnl)}) "
        f"before entry <= firm limit -{rule.daily_loss_pct}%",
    )


def _near(a: Decimal, b: Decimal, tick: Decimal | None) -> bool:
    return abs(a - b) <= tick if tick is not None and tick > 0 else a == b


def evaluate(
    trade: RuleTradeInput,
    context: Iterable[RuleTradeInput],
    rules: RulesConfig,
    spec_tick_size: Decimal | None,
) -> list[Violation]:
    """All violations of ``trade``; ``context`` may include the trade itself."""
    cfg = rules.rules
    tz = rules.timezone
    others = _others(trade, context)
    out: list[Violation] = []

    if (
        cfg.max_risk_pct.enabled
        and trade.risk_pct is not None
        and trade.risk_pct > cfg.max_risk_pct.value
    ):
        out.append(
            Violation(
                "max_risk_pct",
                f"risk {_fmt(trade.risk_pct)}% > limit {cfg.max_risk_pct.value}%",
            )
        )

    for weekly in (False, True):
        risk = _period_risk(trade, others, rules, weekly)
        if risk is not None:
            out.append(risk)

    firm_loss = _firm_daily_loss(trade, others)
    if firm_loss is not None:
        out.append(firm_loss)

    if cfg.max_trades_per_week.enabled:
        week = _week_start(trade.open_time, tz)
        order = (trade.open_time, trade.key)
        n = 1 + sum(
            1
            for t in others
            if _week_start(t.open_time, tz) == week and (t.open_time, t.key) < order
        )
        if n > cfg.max_trades_per_week.value:
            out.append(
                Violation(
                    "max_trades_per_week",
                    f"trade #{n} of the week > limit {cfg.max_trades_per_week.value}",
                )
            )

    if cfg.max_reentries_per_idea.enabled and trade.is_reentry and trade.session is not None:
        day = _local_day(trade.open_time, tz)
        order = (trade.open_time, trade.key)
        count = 1 + sum(
            1
            for t in others
            if t.is_reentry
            and t.symbol == trade.symbol
            and t.direction == trade.direction
            and t.session == trade.session
            and _local_day(t.open_time, tz) == day
            and (t.open_time, t.key) < order
        )
        if count > cfg.max_reentries_per_idea.value:
            out.append(
                Violation(
                    "max_reentries_per_idea",
                    f"re-entry #{count} of this idea > limit {cfg.max_reentries_per_idea.value}",
                )
            )

    if (
        cfg.min_planned_rr.enabled
        and trade.planned_rr is not None
        and trade.planned_rr < cfg.min_planned_rr.value
    ):
        out.append(
            Violation(
                "min_planned_rr",
                f"planned RR {_fmt(trade.planned_rr)} < minimum {cfg.min_planned_rr.value}",
            )
        )

    if cfg.entry_session.enabled and trade.session is not None:
        window = rules.session(trade.session)
        if trade.session == OUTSIDE or (window is not None and not window.entries_allowed):
            out.append(
                Violation("entry_session", f"entry in session {trade.session} (not allowed)")
            )

    qm = cfg.qm_not_in_ny
    if (
        qm.enabled
        and trade.entry_model is not None
        and trade.entry_model == qm.entry_model
        and trade.session == qm.session
    ):
        out.append(Violation("qm_not_in_ny", f"entry model {qm.entry_model} in {qm.session}"))

    if cfg.no_breakeven.enabled:
        detail = _breakeven(trade, spec_tick_size)
        if detail is not None:
            out.append(Violation("no_breakeven", detail))

    return out


def _breakeven(trade: RuleTradeInput, tick: Decimal | None) -> str | None:
    entry, initial = trade.entry_price, trade.initial_sl
    if entry is None or initial is None or _near(initial, entry, tick):
        return None
    last = trade.last_sl
    if last is not None and last != initial and _near(last, entry, tick):
        return f"SL moved from {initial} to {last} (entry {entry})"
    for deal in trade.exit_deals:
        if deal.reason == "sl" and _near(deal.price, entry, tick):
            return f"stopped out at {deal.price} near entry {entry} (initial SL {initial})"
    return None

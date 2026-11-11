"""Cross-trade derived fields: re-entry flags and auto rule violations (PRD 6.9).

Used by the MT5 sync and by PATCH /api/trades/{id} (user-entered initial SL), so both
paths produce identical results. Rules depend on other trades of the same account and
local Mon-Sun week (daily/weekly stops, trades per week, re-entries), so the whole week of
the earliest changed trade onward is recomputed. Idempotent; flushes, never commits.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.config_files.loader import ConfigError
from app.config_files.rules import RulesConfig, get_rules
from app.domain.metrics import ReentryCandidate, reentry_flags
from app.domain.rules import RuleExitDeal, RuleTradeInput, evaluate
from app.domain.sessions import to_local
from app.models import Account, SymbolSpec, Trade
from app.services.violations import apply_auto_violations

logger = logging.getLogger(__name__)


def week_start_utc(moment: datetime, tz: str) -> datetime:
    """UTC instant of local Monday 00:00 of the week containing ``moment``."""
    day = to_local(moment, tz).date()
    monday = day - timedelta(days=day.weekday())
    return datetime.combine(monday, time(0), tzinfo=ZoneInfo(tz)).astimezone(UTC)


def _rule_input(trade: Trade, account_size: Decimal | None) -> RuleTradeInput:
    return RuleTradeInput(
        key=trade.id,
        account_id=trade.account_id,
        symbol=trade.symbol,
        direction=trade.direction,
        open_time=trade.open_time,
        close_time=trade.close_time,
        session=trade.session,
        net_pnl=trade.net_pnl,
        account_size=account_size,
        risk_pct=trade.risk_pct,
        planned_rr=trade.planned_rr,
        entry_price=trade.entry_price,
        last_sl=trade.last_sl,
        initial_sl=trade.initial_sl,
        exit_deals=tuple(RuleExitDeal(d.price, d.reason) for d in trade.exit_deals),
        entry_model=trade.entry_model,
        is_reentry=trade.is_reentry,
    )


def recompute_rules(
    session: Session, account_id: int, since_utc: datetime, rules: RulesConfig
) -> int:
    """Re-entry flags and auto violations of the account's trades opened from the local
    Monday of ``since_utc``'s week onward. Returns the number of trades evaluated."""
    session.flush()
    tz = rules.timezone
    start = week_start_utc(since_utc, tz)
    # Context: everything opened or closed in the period (a trade opened last week and
    # closed this week counts in this week's P&L).
    trades = session.scalars(
        select(Trade)
        .where(
            Trade.account_id == account_id,
            or_(Trade.open_time >= start, Trade.close_time >= start),
        )
        .options(selectinload(Trade.exit_deals))
        .order_by(Trade.open_time, Trade.id)
    ).all()
    targets = [t for t in trades if t.open_time >= start]
    if not targets:
        return 0

    flags = reentry_flags(
        (
            ReentryCandidate(
                key=t.id,
                account_id=t.account_id,
                symbol=t.symbol,
                direction=t.direction,
                session=t.session,
                open_time=t.open_time,
                close_time=t.close_time,
                net_pnl=t.net_pnl,
            )
            for t in trades
        ),
        tz,
    )
    for trade in targets:
        trade.is_reentry = flags.get(trade.id, False)

    ticks = {
        spec.symbol: spec.tick_size
        for spec in session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account_id))
    }
    # Rule percentages are % of the account size (M5-10), never of a balance.
    account_size = session.scalar(select(Account.reference_balance).where(Account.id == account_id))
    context = [_rule_input(t, account_size) for t in trades]
    for trade in targets:
        # Specs are keyed by the broker name; trade.symbol is canonical (M5-08).
        tick = ticks.get(trade.broker_symbol)
        violations = evaluate(_rule_input(trade, account_size), context, rules, tick)
        apply_auto_violations(session, trade.id, violations)
    return len(targets)


def recompute_rules_for_trade(session: Session, trade: Trade, reason: str) -> bool:
    """Recompute after a user edit of ``trade``. A broken rules.yaml does not block the
    edit: it is logged at ERROR and violations catch up on the next sync. Returns False then.
    """
    try:
        rules = get_rules()
    except ConfigError as exc:
        logger.error(
            "Trade %s: violations not recomputed after %s, rules.yaml is invalid: %s",
            trade.id,
            reason,
            exc,
        )
        return False
    recompute_rules(session, trade.account_id, trade.open_time, rules)
    return True

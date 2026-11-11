"""Recompute everything that depends on the account size (docs/api.md M5-10, PRD 6.8/6.9).

risk_pct, pnl_pct and the rule percentages are % of ``accounts.reference_balance``. When the
size changes (PATCH /api/accounts/{id}) the account's stored percentages and auto rule
violations are recomputed in the same transaction; the worker does it for every account once
at start (idempotent; the tables are small). Rule violations reuse
``app.services.trade_rules.recompute_rules`` (the sync / symbol-map path).
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config_files.loader import ConfigError
from app.config_files.rules import get_rules
from app.domain import metrics
from app.models import Account, Trade
from app.services.trade_rules import recompute_rules

logger = logging.getLogger(__name__)


def recompute_account(db: Session, account_id: int) -> int:
    """risk_pct / pnl_pct (closed trades only) of every trade of the account from its size,
    then the auto rule violations of all its trades. Flushes, never commits.

    Returns the account's trade count. Raises ConfigError for a broken rules.yaml (the
    caller decides: the API answers config_error, the worker start logs ERROR).
    """
    rules = get_rules()  # before any change: a broken rules.yaml changes nothing
    db.flush()
    size = db.scalar(select(Account.reference_balance).where(Account.id == account_id))
    trades = db.scalars(select(Trade).where(Trade.account_id == account_id)).all()
    for trade in trades:
        trade.risk_pct = metrics.risk_pct(trade.risk_amount, size)
        closed = trade.close_time is not None
        trade.pnl_pct = metrics.pnl_pct(trade.net_pnl, size) if closed else None
    earliest = db.scalar(select(func.min(Trade.open_time)).where(Trade.account_id == account_id))
    if earliest is not None:
        recompute_rules(db, account_id, earliest, rules)
    db.flush()
    return len(trades)


def recompute_all(session_factory: sessionmaker[Session]) -> int | None:
    """recompute_account for every account, each in its own savepoint; commits once.

    A failing account (e.g. a size so small its percents overflow NUMERIC(10,4)) is logged at
    ERROR with its id and skipped; the others are still recomputed and committed. Returns the
    trade count of the accounts that succeeded, or None when the whole step fails (DB down,
    broken rules.yaml; logged at ERROR, rolled back). Never raises, so the worker start is never
    blocked.
    """
    try:
        get_rules()  # a broken rules.yaml fails the step once, not every account
        with session_factory() as db:
            ids = db.scalars(select(Account.id).order_by(Account.id)).all()
            total = sum(_recompute_in_savepoint(db, account_id) for account_id in ids)
            db.commit()
    except Exception:
        logger.exception("Risk base recompute (account size percents and rules) failed")
        return None
    else:
        logger.info("Risk base recompute: %s trades of %s accounts", total, len(ids))
        return total


def _recompute_in_savepoint(db: Session, account_id: int) -> int:
    """The account's trade count, or 0 after logging and rolling back its savepoint."""
    try:
        with db.begin_nested():
            return recompute_account(db, account_id)
    except ConfigError:
        raise  # rules.yaml broke mid-run: the whole step fails
    except Exception:
        logger.exception(
            "Risk base recompute: account %s skipped (its values are kept)", account_id
        )
        return 0

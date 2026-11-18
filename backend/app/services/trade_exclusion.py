"""M8-01: exclude a trade from strategy statistics and revert it (docs/api.md "M8-01").

Only the owner-side columns (``excluded_*``) and the history table change; MT5 data never
does. Rules, dashboard P&L and stops keep reading every trade, so nothing is recomputed.
Flushes, never commits.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Trade, TradeStatsExclusion
from app.models.enums import StatsExclusionAction

logger = logging.getLogger(__name__)


def exclude_trade(db: Session, trade: Trade, reason: str, now: datetime) -> None:
    """Leave ``trade`` out of strategy statistics; 409 ``already_excluded`` if it is."""
    if trade.excluded_from_stats:
        raise ApiError(409, "already_excluded", "Trade is already excluded", {"id": trade.id})
    trade.excluded_from_stats = True
    trade.excluded_reason = reason
    trade.excluded_at = now
    _history(db, trade, StatsExclusionAction.EXCLUDE, reason, now)
    logger.info("Trade %s excluded from statistics", trade.id)


def include_trade(db: Session, trade: Trade, reason: str | None, now: datetime) -> None:
    """Count ``trade`` again; 409 ``not_excluded`` if it is counted."""
    if not trade.excluded_from_stats:
        raise ApiError(409, "not_excluded", "Trade is not excluded", {"id": trade.id})
    trade.excluded_from_stats = False
    trade.excluded_reason = None
    trade.excluded_at = None
    _history(db, trade, StatsExclusionAction.INCLUDE, reason, now)
    logger.info("Trade %s returned to statistics", trade.id)


def _history(
    db: Session, trade: Trade, action: StatsExclusionAction, reason: str | None, now: datetime
) -> None:
    db.add(
        TradeStatsExclusion(
            trade_id=trade.id, action=action.value, reason=reason, created_at=now, updated_at=now
        )
    )
    db.flush()

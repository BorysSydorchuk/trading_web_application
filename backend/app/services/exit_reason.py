"""Apply the M8-09 exit-reason prefill to a Trade row (sync and backfill share it).

Rules are in `app.domain.exit_reason`; this module only writes the two columns, with a
guarded UPDATE: PostgreSQL re-checks the WHERE on the latest committed row, so an owner
value saved concurrently (between our read and our write) always wins.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.domain.exit_reason import (
    AUTO_SOURCES,
    ClosingDeal,
    resolve_prefill,
    suggest_exit_reason,
)
from app.models import Trade

logger = logging.getLogger(__name__)


def _guard(trade: Trade) -> ColumnElement[bool]:
    """The row state our decision was based on (empty, or still prefilled)."""
    if trade.exit_reason_source in AUTO_SOURCES:
        return Trade.exit_reason_source.in_(AUTO_SOURCES)
    return and_(Trade.exit_reason.is_(None), Trade.exit_reason_source.is_(None))


def prefill_exit_reason(
    session: Session, trade: Trade, deals: Sequence[ClosingDeal], tick_size: Decimal | None
) -> str | None:
    """Write exit_reason/exit_reason_source when allowed; returns the source written or None.

    Only closed, already flushed trades. Never touches an owner value or a value from
    before M8-09, also when the owner saves one concurrently.
    """
    if trade.close_time is None or trade.id is None:
        return None
    suggestion = suggest_exit_reason(
        deals, initial_sl=trade.initial_sl, tp=trade.tp, tick_size=tick_size
    )
    resolved = resolve_prefill(trade.exit_reason, trade.exit_reason_source, suggestion)
    if resolved is None or resolved == (trade.exit_reason, trade.exit_reason_source):
        return None
    value, source = resolved
    result = session.execute(
        update(Trade)
        .where(Trade.id == trade.id, _guard(trade))
        .values(exit_reason=value, exit_reason_source=source)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        logger.info("Trade %s: exit reason changed meanwhile, prefill skipped", trade.id)
        session.expire(trade, ["exit_reason", "exit_reason_source"])
        return None
    set_committed_value(trade, "exit_reason", value)
    set_committed_value(trade, "exit_reason_source", source)
    return source

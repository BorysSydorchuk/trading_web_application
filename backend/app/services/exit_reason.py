"""Apply the M8-09 exit-reason prefill to a Trade row (sync and backfill share it).

Rules are in `app.domain.exit_reason`; this module only reads/writes the two columns.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.domain.exit_reason import ClosingDeal, resolve_prefill, suggest_exit_reason
from app.models import Trade


def prefill_exit_reason(
    trade: Trade, deals: Sequence[ClosingDeal], tick_size: Decimal | None
) -> str | None:
    """Set exit_reason/exit_reason_source when allowed; returns the source written or None.

    Only closed trades. Never touches an owner value or a value from before M8-09.
    """
    if trade.close_time is None:
        return None
    suggestion = suggest_exit_reason(
        deals, initial_sl=trade.initial_sl, tp=trade.tp, tick_size=tick_size
    )
    resolved = resolve_prefill(trade.exit_reason, trade.exit_reason_source, suggestion)
    if resolved is None or resolved == (trade.exit_reason, trade.exit_reason_source):
        return None
    trade.exit_reason, trade.exit_reason_source = resolved
    return resolved[1]

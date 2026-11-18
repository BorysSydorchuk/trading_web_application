"""Inbox counts (docs/api.md): trades waiting for the user on accounts that are not archived,
except trades excluded from statistics
(M8-01), except «needs SL»: the risk rules still need the initial SL.

Shared by `GET /api/inbox/counts` and `GET /api/dashboard`.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Account, Trade
from app.models.enums import AccountStatus, TradeStatus
from app.schemas.trades import InboxCounts

INBOX_STATUSES = (TradeStatus.NEEDS_SL, TradeStatus.NEEDS_DESCRIPTION, TradeStatus.DRAFT)


def count_inbox(db: Session) -> InboxCounts:
    rows = db.execute(
        select(Trade.status, func.count())
        .join(Account, Account.id == Trade.account_id)
        .where(
            Account.status != AccountStatus.ARCHIVED.value,
            Trade.status.in_([s.value for s in INBOX_STATUSES]),
            # M8-01: an excluded trade needs no strategy description, but a missing
            # initial SL is still asked for (the risk rules need it).
            or_(
                Trade.status == TradeStatus.NEEDS_SL.value,
                Trade.excluded_from_stats.is_(False),
            ),
        )
        .group_by(Trade.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in rows}
    return InboxCounts(
        needs_sl=counts.get(TradeStatus.NEEDS_SL.value, 0),
        needs_description=counts.get(TradeStatus.NEEDS_DESCRIPTION.value, 0),
        draft=counts.get(TradeStatus.DRAFT.value, 0),
    )

"""Inbox counts (docs/api.md): trades waiting for the user on accounts that are not archived.

Shared by `GET /api/inbox/counts` and `GET /api/dashboard`.
"""

from __future__ import annotations

from sqlalchemy import func, select
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
        )
        .group_by(Trade.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in rows}
    return InboxCounts(
        needs_sl=counts.get(TradeStatus.NEEDS_SL.value, 0),
        needs_description=counts.get(TradeStatus.NEEDS_DESCRIPTION.value, 0),
        draft=counts.get(TradeStatus.DRAFT.value, 0),
    )

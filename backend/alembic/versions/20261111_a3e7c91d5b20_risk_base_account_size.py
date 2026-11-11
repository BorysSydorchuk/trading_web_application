"""Risk base = account size (hand-written, M5-10).

`accounts.reference_balance` becomes the account size every percentage divides by
(PRD 6.8/6.9, DECISIONS 2026-11-11). Upgrade:
1. backfill ``reference_balance = starting_balance`` where NULL (set values are kept);
2. recompute ``trades.risk_pct`` and ``trades.pnl_pct`` from the account size at 4 dp
   (PostgreSQL ``round(numeric, 4)`` rounds half away from zero = ROUND_HALF_UP, also for
   negative values); NULL risk / P&L stay NULL; open trades get no P&L % (like the sync and
   ``risk_base.recompute_account``). Accounts whose size is not a positive
   finite number keep their stored percents (no division by zero / NaN);
3. make ``reference_balance`` NOT NULL. No CHECK constraint: the API validates > 0 and the
   calculator guards a non-positive / NaN size.

Downgrade makes the column nullable again; values and the recomputed percents stay.

Revision ID: a3e7c91d5b20
Revises: f6ea0d1af419
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3e7c91d5b20"
down_revision: str | Sequence[str] | None = "f6ea0d1af419"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(18, 2)

_RECOMPUTE_PERCENTS = """
UPDATE trades AS t
SET risk_pct = round(t.risk_amount * 100 / a.reference_balance, 4),
    pnl_pct = CASE
        WHEN t.close_time IS NOT NULL THEN round(t.net_pnl * 100 / a.reference_balance, 4)
    END
FROM accounts AS a
WHERE a.id = t.account_id
  AND a.reference_balance > 0
  AND a.reference_balance <> 'NaN'::numeric
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE accounts SET reference_balance = starting_balance "
            "WHERE reference_balance IS NULL"
        )
    )
    op.execute(sa.text(_RECOMPUTE_PERCENTS))
    op.alter_column("accounts", "reference_balance", existing_type=_MONEY, nullable=False)


def downgrade() -> None:
    op.alter_column("accounts", "reference_balance", existing_type=_MONEY, nullable=True)

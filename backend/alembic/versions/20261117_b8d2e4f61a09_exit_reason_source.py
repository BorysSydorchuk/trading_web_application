"""Exit reason prefill from MT5 (M8-09).

Adds ``trades.exit_reason_source`` (VARCHAR(20) NULL, CHECK mt5_reason / price_match / owner):
who set ``exit_reason``. Existing rows stay NULL: values entered before M8-09 are never
overwritten. Adds ``trade_exit_deals.reason_code`` (INTEGER NULL): the raw MT5 DEAL_REASON
next to the mapped ``reason`` key; NULL for deals stored before M8-09.

No data is changed here; empty exit reasons are filled by ``python -m
app.tools.backfill_exit_reason --apply`` (reads only stored deals, no MT5 call).
Downgrade drops both columns (the prefill marker is lost, values stay).

Revision ID: b8d2e4f61a09
Revises: cdb0477c3b70
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d2e4f61a09"
down_revision: str | Sequence[str] | None = "cdb0477c3b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("exit_reason_source", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_trades_exit_reason_source_valid"),
        "trades",
        "exit_reason_source IN ('mt5_reason', 'price_match', 'owner')",
    )
    op.add_column("trade_exit_deals", sa.Column("reason_code", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("trade_exit_deals", "reason_code")
    op.drop_constraint(op.f("ck_trades_exit_reason_source_valid"), "trades", type_="check")
    op.drop_column("trades", "exit_reason_source")

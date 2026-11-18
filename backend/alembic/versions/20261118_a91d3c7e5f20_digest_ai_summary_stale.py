"""Saved digests follow exclude / include (M8-01b).

Adds ``digests.ai_summary_stale_at`` (TIMESTAMPTZ NULL): the numbers were recomputed after
the AI summary was written; cleared by a new summary. Existing digests get NULL (not stale);
no data is changed. Downgrade drops the column (the stale marks are lost).

Revision ID: a91d3c7e5f20
Revises: e4a7c2f9b315
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a91d3c7e5f20"
down_revision: str | Sequence[str] | None = "e4a7c2f9b315"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "digests",
        sa.Column("ai_summary_stale_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("digests", "ai_summary_stale_at")

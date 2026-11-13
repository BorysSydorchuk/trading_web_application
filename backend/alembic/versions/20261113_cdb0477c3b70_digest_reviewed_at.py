"""Digest review date (hand-written, M6-06a).

Adds ``digests.reviewed_at`` (timestamptz NULL): when the review texts were last changed while
at least one stays non-empty (docs/api.md "M6"). Regenerating a digest rewrites ``updated_at``,
so the review date needs its own column. Upgrade backfills ``reviewed_at = updated_at`` for
digests with a non-empty what_worked / what_to_fix / focus_next (NULL and '' are empty;
ai_summary does not count). Downgrade drops the column.

Revision ID: cdb0477c3b70
Revises: a3e7c91d5b20
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cdb0477c3b70"
down_revision: str | Sequence[str] | None = "a3e7c91d5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE digests
SET reviewed_at = updated_at
WHERE coalesce(what_worked, '') <> ''
   OR coalesce(what_to_fix, '') <> ''
   OR coalesce(focus_next, '') <> ''
"""


def upgrade() -> None:
    op.add_column("digests", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text(_BACKFILL))


def downgrade() -> None:
    op.drop_column("digests", "reviewed_at")

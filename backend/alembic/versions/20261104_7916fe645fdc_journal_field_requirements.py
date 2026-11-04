"""journal_field_requirements + journal_requirements_state (hand-written)

M3 "New required fields" (docs/api.md): the server remembers when each journal field
became `required: true`. The table starts empty; the app's first sync fills it with
required_since = 1970-01-01 for every field required at that moment and records that in
the single `journal_requirements_state` row seeded here (initial_fill_at NULL = not yet).

Revision ID: 7916fe645fdc
Revises: 3c9a1e5d7f20
Create Date: 2026-11-04 15:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7916fe645fdc"
down_revision: str | Sequence[str] | None = "3c9a1e5d7f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "journal_field_requirements",
        sa.Column("key", sa.String(length=63), nullable=False),
        sa.Column("required_since", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_journal_field_requirements")),
    )
    state = op.create_table(
        "journal_requirements_state",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("initial_fill_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_journal_requirements_state_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_requirements_state")),
    )
    op.bulk_insert(state, [{"id": 1, "initial_fill_at": None}])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("journal_requirements_state")
    op.drop_table("journal_field_requirements")

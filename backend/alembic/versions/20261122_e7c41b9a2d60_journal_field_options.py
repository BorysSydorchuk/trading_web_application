"""Editable journal option lists: new empty table ``journal_field_options``.

No existing table or trade value changes. A field without rows keeps using its defaults from
config/journal_fields.yaml; the rows are created on the owner's first edit of that list.
Downgrade drops the table: owner-added options, labels, order and synonyms are lost, and a
trade that stores an owner-added key then shows the raw key.

Revision ID: e7c41b9a2d60
Revises: d3b9f1a7c2e4
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c41b9a2d60"
down_revision: str | None = "d3b9f1a7c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journal_field_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_key", sa.String(length=63), nullable=False),
        sa.Column("value", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "synonyms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "jsonb_typeof(synonyms) = 'array'",
            name=op.f("ck_journal_field_options_synonyms_is_array"),
        ),
        sa.CheckConstraint(
            "length(btrim(label)) > 0", name=op.f("ck_journal_field_options_label_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_field_options")),
        sa.UniqueConstraint(
            "field_key", "value", name=op.f("uq_journal_field_options_field_key_value")
        ),
    )


def downgrade() -> None:
    op.drop_table("journal_field_options")

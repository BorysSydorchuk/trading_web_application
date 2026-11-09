"""Nullable broker sizing metadata and margin persistence (hand-written).

Revision ID: c8a41e62b903
Revises: b6d41a9e2c57
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a41e62b903"
down_revision: str | Sequence[str] | None = "b6d41a9e2c57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No default or backfill: old generic tick values/digits are not these fields.
    op.add_column("symbol_specs", sa.Column("point", sa.Numeric(20, 8), nullable=True))
    op.add_column("symbol_specs", sa.Column("tick_value_loss", sa.Numeric(20, 8), nullable=True))
    op.create_table(
        "calculator_margin_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(4), nullable=False),
        sa.Column("margin", sa.Numeric(28, 8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spec_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "symbol",
            "direction",
            name=op.f("uq_calculator_margin_samples_account_id_symbol_direction"),
        ),
        sa.CheckConstraint(
            "direction IN ('buy', 'sell')",
            name=op.f("ck_calculator_margin_samples_direction_valid"),
        ),
        sa.CheckConstraint(
            "btrim(symbol) <> ''", name=op.f("ck_calculator_margin_samples_symbol_not_empty")
        ),
        sa.CheckConstraint(
            "length(btrim(currency)) = 3", name=op.f("ck_calculator_margin_samples_currency_valid")
        ),
        sa.CheckConstraint(
            "btrim(signature) <> ''", name=op.f("ck_calculator_margin_samples_signature_not_empty")
        ),
        sa.CheckConstraint(
            "margin >= 0 AND margin::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name=op.f("ck_calculator_margin_samples_margin_valid"),
        ),
        sa.CheckConstraint(
            "volume > 0 AND volume::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name=op.f("ck_calculator_margin_samples_volume_valid"),
        ),
        sa.CheckConstraint(
            "price > 0 AND price::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name=op.f("ck_calculator_margin_samples_price_valid"),
        ),
    )
    op.create_table(
        "calculator_margin_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(4), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=False),
        sa.Column("entry", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("margin", sa.Numeric(28, 8), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('buy', 'sell')",
            name=op.f("ck_calculator_margin_requests_direction_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'expired')",
            name=op.f("ck_calculator_margin_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "btrim(symbol) <> ''", name=op.f("ck_calculator_margin_requests_symbol_not_empty")
        ),
        sa.CheckConstraint(
            "length(btrim(currency)) = 3", name=op.f("ck_calculator_margin_requests_currency_valid")
        ),
        sa.CheckConstraint(
            "btrim(signature) <> ''", name=op.f("ck_calculator_margin_requests_signature_not_empty")
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR btrim(error_code) <> ''",
            name=op.f("ck_calculator_margin_requests_error_not_empty"),
        ),
        sa.CheckConstraint(
            "volume > 0 AND volume::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name=op.f("ck_calculator_margin_requests_volume_valid"),
        ),
        sa.CheckConstraint(
            "entry > 0 AND entry::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name=op.f("ck_calculator_margin_requests_entry_valid"),
        ),
        sa.CheckConstraint(
            "margin IS NULL OR (margin >= 0 "
            "AND margin::text NOT IN ('NaN', 'Infinity', '-Infinity'))",
            name=op.f("ck_calculator_margin_requests_margin_valid"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at "
            "AND (started_at IS NULL OR started_at >= created_at) "
            "AND (finished_at IS NULL OR finished_at >= created_at) "
            "AND (started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at)",
            name=op.f("ck_calculator_margin_requests_timestamps_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL "
            "AND margin IS NULL AND error_code IS NULL) OR "
            "(status = 'processing' AND started_at IS NOT NULL AND finished_at IS NULL "
            "AND margin IS NULL AND error_code IS NULL) OR "
            "(status = 'done' AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND margin IS NOT NULL AND error_code IS NULL) OR "
            "(status IN ('failed', 'expired') AND finished_at IS NOT NULL "
            "AND margin IS NULL AND error_code IS NOT NULL)",
            name=op.f("ck_calculator_margin_requests_result_matches_status"),
        ),
    )
    op.create_index(
        "ix_calculator_margin_requests_queue",
        "calculator_margin_requests",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "ix_calculator_margin_requests_account_id", "calculator_margin_requests", ["account_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calculator_margin_requests_account_id", table_name="calculator_margin_requests"
    )
    op.drop_index("ix_calculator_margin_requests_queue", table_name="calculator_margin_requests")
    op.drop_table("calculator_margin_requests")
    op.drop_table("calculator_margin_samples")
    op.drop_column("symbol_specs", "tick_value_loss")
    op.drop_column("symbol_specs", "point")

"""Exclude a trade from strategy statistics (M8-01).

Adds ``trades.excluded_from_stats`` (BOOLEAN NOT NULL DEFAULT false), ``trades.excluded_reason``
(TEXT) and ``trades.excluded_at`` (TIMESTAMPTZ) with a CHECK that the flag, reason and time
are set together (reason never blank). Existing trades stay counted (false, NULL, NULL);
no data is changed.
Adds the history table ``trade_stats_exclusions`` (exclude / include actions, reason, time).
Downgrade drops the table and the columns (exclusions and their history are lost).

Revision ID: e4a7c2f9b315
Revises: b8d2e4f61a09
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c2f9b315"
down_revision: str | Sequence[str] | None = "b8d2e4f61a09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("excluded_from_stats", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("trades", sa.Column("excluded_reason", sa.Text(), nullable=True))
    op.add_column("trades", sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_trades_stats_exclusion_consistent"),
        "trades",
        "excluded_from_stats = (excluded_reason IS NOT NULL)"
        " AND excluded_from_stats = (excluded_at IS NOT NULL)"
        " AND (excluded_reason IS NULL OR length(btrim(excluded_reason)) > 0)",
    )
    op.create_table(
        "trade_stats_exclusions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('exclude', 'include')",
            name=op.f("ck_trade_stats_exclusions_action_valid"),
        ),
        sa.CheckConstraint(
            "action <> 'exclude' OR length(btrim(reason)) > 0",
            name=op.f("ck_trade_stats_exclusions_exclude_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
            name=op.f("fk_trade_stats_exclusions_trade_id_trades"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_stats_exclusions")),
    )
    op.create_index(
        op.f("ix_trade_stats_exclusions_trade_id"), "trade_stats_exclusions", ["trade_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trade_stats_exclusions_trade_id"), table_name="trade_stats_exclusions")
    op.drop_table("trade_stats_exclusions")
    op.drop_constraint(op.f("ck_trades_stats_exclusion_consistent"), "trades", type_="check")
    op.drop_column("trades", "excluded_at")
    op.drop_column("trades", "excluded_reason")
    op.drop_column("trades", "excluded_from_stats")

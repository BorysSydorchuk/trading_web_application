"""Cross-currency loss value: fx_rates and the MT5 loss-per-tick check (hand-written, M5-09).

Adds table fx_rates (latest profit -> account currency rate per account, written by the
worker each sync) and nullable symbol_specs.mt5_loss_per_tick / mt5_loss_per_tick_at (the
order_calc_profit check, both NULL or both set). No backfill: rates and checks only exist
after the next sync; stored trades need no change (docs/api.md M5-09).

Downgrade drops the table and the columns; their data is discarded (the next sync after a
re-upgrade writes them again).

Revision ID: f6ea0d1af419
Revises: 5d2e8b1c4a90
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6ea0d1af419"
down_revision: str | Sequence[str] | None = "5d2e8b1c4a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _positive_finite(column: str) -> str:
    return f"{column} > 0 AND {column}::text NOT IN ('NaN', 'Infinity', '-Infinity')"


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_currency", sa.String(10), nullable=False),
        sa.Column("to_currency", sa.String(10), nullable=False),
        sa.Column("pair", sa.String(50), nullable=False),
        sa.Column("inverted", sa.Boolean(), nullable=False),
        sa.Column("bid", sa.Numeric(20, 8), nullable=False),
        sa.Column("ask", sa.Numeric(20, 8), nullable=False),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("rate_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "from_currency",
            "to_currency",
            name=op.f("uq_fx_rates_account_id_from_currency_to_currency"),
        ),
        sa.CheckConstraint(
            "btrim(from_currency) <> '' AND btrim(to_currency) <> '' "
            "AND upper(from_currency) <> upper(to_currency)",
            name=op.f("ck_fx_rates_currencies_valid"),
        ),
        sa.CheckConstraint("btrim(pair) <> ''", name=op.f("ck_fx_rates_pair_not_empty")),
        sa.CheckConstraint(_positive_finite("bid"), name=op.f("ck_fx_rates_bid_valid")),
        sa.CheckConstraint(_positive_finite("ask"), name=op.f("ck_fx_rates_ask_valid")),
        sa.CheckConstraint(_positive_finite("rate"), name=op.f("ck_fx_rates_rate_valid")),
    )
    op.add_column("symbol_specs", sa.Column("mt5_loss_per_tick", sa.Numeric(20, 8), nullable=True))
    op.add_column(
        "symbol_specs",
        sa.Column("mt5_loss_per_tick_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_symbol_specs_mt5_loss_per_tick_pair"),
        "symbol_specs",
        "(mt5_loss_per_tick IS NULL) = (mt5_loss_per_tick_at IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_symbol_specs_mt5_loss_per_tick_valid"),
        "symbol_specs",
        "mt5_loss_per_tick IS NULL OR (mt5_loss_per_tick > 0 "
        "AND mt5_loss_per_tick::text NOT IN ('NaN', 'Infinity', '-Infinity'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_symbol_specs_mt5_loss_per_tick_valid"), "symbol_specs", type_="check"
    )
    op.drop_constraint(
        op.f("ck_symbol_specs_mt5_loss_per_tick_pair"), "symbol_specs", type_="check"
    )
    op.drop_column("symbol_specs", "mt5_loss_per_tick_at")
    op.drop_column("symbol_specs", "mt5_loss_per_tick")
    op.drop_table("fx_rates")

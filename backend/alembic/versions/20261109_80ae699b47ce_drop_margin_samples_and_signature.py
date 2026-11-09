"""Drop calculator margin samples and request signatures (hand-written).

The latest done margin request is the offline sample (PM scope check 2026-11-09), so the
samples table and the spec-signature columns are not needed.

Revision ID: 80ae699b47ce
Revises: c8a41e62b903
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "80ae699b47ce"
down_revision: str | Sequence[str] | None = "c8a41e62b903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUESTS = "calculator_margin_requests"
_SIGNATURE_CHECK = "ck_calculator_margin_requests_signature_not_empty"
# Downgrade fill for existing requests. Never a hex digest (contains ':'), so it can never
# equal a real spec signature and never de-duplicates against a new request; per-row (id)
# so two old rows never look identical. Passes btrim(signature) <> ''.
_DOWNGRADE_FILL = "UPDATE calculator_margin_requests SET signature = 'downgraded:' || id::text"


def upgrade() -> None:
    op.drop_constraint(op.f(_SIGNATURE_CHECK), _REQUESTS, type_="check")
    op.drop_column(_REQUESTS, "signature")
    op.drop_table("calculator_margin_samples")


def downgrade() -> None:
    _create_margin_samples()
    # NOT NULL column on a table that may already hold rows: add nullable, fill, then tighten.
    # Postgres appends the column, so its position differs from c8a41e62b903 (no effect on
    # names, types or constraints).
    op.add_column(_REQUESTS, sa.Column("signature", sa.String(64), nullable=True))
    op.execute(sa.text(_DOWNGRADE_FILL))
    op.alter_column(_REQUESTS, "signature", existing_type=sa.String(64), nullable=False)
    op.create_check_constraint(op.f(_SIGNATURE_CHECK), _REQUESTS, "btrim(signature) <> ''")


def _create_margin_samples() -> None:
    """Exactly the table c8a41e62b903 created (data is not restored)."""
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

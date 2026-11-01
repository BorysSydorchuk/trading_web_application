"""drop accounts.password_ref, add trades.initial_sl_source (hand-written)

Investor passwords live in `.env` as `MT5_PASSWORD_<login>` (DECISIONS.md 2026-11-01),
so the per-account key name is no longer stored. `initial_sl_source` records where the
initial SL came from: deal | order | position | user.

Revision ID: 7b0cc62b13f4
Revises: fb4301190096
Create Date: 2026-11-01 10:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b0cc62b13f4"
down_revision: str | Sequence[str] | None = "fb4301190096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("accounts", "password_ref")
    op.add_column("trades", sa.Column("initial_sl_source", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_trades_initial_sl_source_valid"),
        "trades",
        "initial_sl_source IN ('deal', 'order', 'position', 'user')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_trades_initial_sl_source_valid"), "trades", type_="check")
    op.drop_column("trades", "initial_sl_source")
    op.add_column("accounts", sa.Column("password_ref", sa.String(length=100), nullable=True))

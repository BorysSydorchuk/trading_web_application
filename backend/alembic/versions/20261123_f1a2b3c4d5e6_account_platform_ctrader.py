"""Accounts gain a platform: ``mt5`` (every existing row) or ``ctrader``.

Additive: existing rows become ``mt5`` through the server default and keep every value. A
cTrader account stores its ctidTraderAccountId and live/demo flag; an MT5 account has neither.
Downgrade refuses while cTrader accounts exist: without these columns they would look like MT5
accounts with no terminal.

Revision ID: f1a2b3c4d5e6
Revises: e7c41b9a2d60
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e7c41b9a2d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("platform", sa.String(length=10), server_default="mt5", nullable=False),
    )
    op.add_column("accounts", sa.Column("ctid_trader_account_id", sa.BigInteger(), nullable=True))
    op.add_column("accounts", sa.Column("ctrader_is_live", sa.Boolean(), nullable=True))
    op.create_check_constraint(
        op.f("ck_accounts_platform_valid"), "accounts", "platform IN ('mt5', 'ctrader')"
    )
    op.create_check_constraint(
        op.f("ck_accounts_platform_fields"),
        "accounts",
        "(platform = 'ctrader' AND ctid_trader_account_id IS NOT NULL "
        "AND ctrader_is_live IS NOT NULL) OR "
        "(platform = 'mt5' AND ctid_trader_account_id IS NULL AND ctrader_is_live IS NULL)",
    )
    op.create_unique_constraint(
        op.f("uq_accounts_ctid_trader_account_id"), "accounts", ["ctid_trader_account_id"]
    )


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM accounts WHERE platform <> 'mt5'"))
    if count:
        raise RuntimeError(
            f"Downgrade refused: {count} cTrader account(s) exist. Delete them first."
        )
    op.drop_constraint(op.f("uq_accounts_ctid_trader_account_id"), "accounts", type_="unique")
    op.drop_constraint(op.f("ck_accounts_platform_fields"), "accounts", type_="check")
    op.drop_constraint(op.f("ck_accounts_platform_valid"), "accounts", type_="check")
    op.drop_column("accounts", "ctrader_is_live")
    op.drop_column("accounts", "ctid_trader_account_id")
    op.drop_column("accounts", "platform")

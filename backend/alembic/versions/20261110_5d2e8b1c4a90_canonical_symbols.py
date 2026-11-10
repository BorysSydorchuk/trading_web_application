"""Broker and canonical symbol columns (hand-written, M5-08).

`config/symbols.yaml` maps canonical names (GER40) to broker names (FundedNext: GER30).
Adds trades.broker_symbol, symbol_specs.canonical_symbol and
calculator_margin_requests.broker_symbol, NOT NULL, backfilled with a copy of `symbol`.
The YAML map is deliberately not applied here: the worker re-applies it to stored rows at
start and every sync cycle (DECISIONS 2026-11-10), so a migration never freezes a map.

Downgrade: before this revision `symbol` held the broker name, so trades and margin requests
get `symbol = broker_symbol` back before the columns are dropped (symbol_specs.symbol always
stayed the broker name).

Revision ID: 5d2e8b1c4a90
Revises: 80ae699b47ce
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d2e8b1c4a90"
down_revision: str | Sequence[str] | None = "80ae699b47ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, new column): the copy of `symbol` each row starts with.
_COLUMNS = (
    ("trades", "broker_symbol"),
    ("symbol_specs", "canonical_symbol"),
    ("calculator_margin_requests", "broker_symbol"),
)
# Tables whose `symbol` became canonical and gets the broker name back on downgrade.
_RESTORE_ON_DOWNGRADE = ("trades", "calculator_margin_requests")


def upgrade() -> None:
    # NOT NULL on tables that may hold rows: add nullable, fill, then tighten.
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.String(50), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET {column} = symbol"))  # noqa: S608 - constants
        op.alter_column(table, column, existing_type=sa.String(50), nullable=False)


def downgrade() -> None:
    for table in _RESTORE_ON_DOWNGRADE:
        op.execute(
            sa.text(f"UPDATE {table} SET symbol = broker_symbol WHERE symbol <> broker_symbol")  # noqa: S608
        )
    for table, column in reversed(_COLUMNS):
        op.drop_column(table, column)

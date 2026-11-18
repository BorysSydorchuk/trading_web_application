"""MAE / MFE per trade (M8-16).

Adds to ``trades``: ``mfe_price``/``mae_price`` (NUMERIC(20,8)), ``mfe_time``/``mae_time``
(TIMESTAMPTZ), ``mfe_points``/``mae_points`` (NUMERIC(14,1)), ``mfe_r``/``mae_r``
(NUMERIC(10,4)), ``excursion_status`` (final | running | unavailable, CHECK),
``excursion_source`` (ticks | m1_ticks, CHECK) and ``excursion_at`` (TIMESTAMPTZ), all NULL
(= not computed yet). No data is changed; values come from the sync and the backfill tool.
Downgrade drops the columns (computed values are lost, MT5 can recompute them).

Revision ID: c6f2a8d4e173
Revises: a91d3c7e5f20
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6f2a8d4e173"
down_revision: str | Sequence[str] | None = "a91d3c7e5f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRICE = sa.Numeric(20, 8)
_POINTS = sa.Numeric(14, 1)
_RATIO = sa.Numeric(10, 4)
_TS = sa.DateTime(timezone=True)
_COLUMNS = (
    ("mfe_price", _PRICE),
    ("mfe_time", _TS),
    ("mfe_points", _POINTS),
    ("mfe_r", _RATIO),
    ("mae_price", _PRICE),
    ("mae_time", _TS),
    ("mae_points", _POINTS),
    ("mae_r", _RATIO),
    ("excursion_status", sa.String(20)),
    ("excursion_source", sa.String(10)),
    ("excursion_at", _TS),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("trades", sa.Column(name, type_, nullable=True))
    op.create_check_constraint(
        op.f("ck_trades_excursion_status_valid"),
        "trades",
        "excursion_status IN ('final', 'running', 'unavailable')",
    )
    op.create_check_constraint(
        op.f("ck_trades_excursion_source_valid"),
        "trades",
        "excursion_source IN ('ticks', 'm1_ticks')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_trades_excursion_source_valid"), "trades", type_="check")
    op.drop_constraint(op.f("ck_trades_excursion_status_valid"), "trades", type_="check")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("trades", name)

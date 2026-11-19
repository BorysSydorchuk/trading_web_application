"""M8-16 migration: MAE/MFE columns on trades follow a91d3c7e5f20; existing trades stay NULL.
Drift / roundtrip / single head: test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config
from tests.test_trade_exclusion_migration import _insert_trade

BEFORE = "a91d3c7e5f20"
COLUMNS = {
    "mfe_price",
    "mfe_time",
    "mfe_points",
    "mfe_r",
    "mae_price",
    "mae_time",
    "mae_points",
    "mae_r",
    "excursion_status",
    "excursion_source",
    "excursion_at",
}


@pytest.fixture(autouse=True)
def _restore_head(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))
    command.upgrade(alembic_config(), "head")


def test_upgrade_leaves_existing_trades_without_values_and_downgrade_drops(
    db_engine: Engine,
) -> None:
    command.downgrade(alembic_config(), BEFORE)
    with db_engine.begin() as conn:
        _insert_trade(conn)

    command.upgrade(alembic_config(), "head")

    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT excursion_status, mfe_r, mae_r FROM trades")).one()
    assert tuple(row) == (None, None, None)

    command.downgrade(alembic_config(), BEFORE)
    columns = {c["name"] for c in inspect(db_engine).get_columns("trades")}
    assert not columns & COLUMNS


def test_check_rejects_an_unknown_status(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        _insert_trade(conn)
    with pytest.raises(Exception, match="excursion_status_valid"), db_engine.begin() as conn:
        conn.execute(text("UPDATE trades SET excursion_status = 'maybe'"))


def test_check_rejects_an_unknown_source(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        _insert_trade(conn)
    with pytest.raises(Exception, match="excursion_source_valid"), db_engine.begin() as conn:
        conn.execute(text("UPDATE trades SET excursion_source = 'm5'"))

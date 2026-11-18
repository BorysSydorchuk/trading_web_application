"""M8-01 migration: trades.excluded_from_stats / excluded_reason / excluded_at plus the
trade_stats_exclusions history table, follows b8d2e4f61a09. Existing trades stay counted.
Drift / roundtrip / single head: test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config

BEFORE = "b8d2e4f61a09"


@pytest.fixture(autouse=True)
def _restore_head(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))
    command.upgrade(alembic_config(), "head")


def _insert_trade(conn: object) -> None:
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO accounts (name, firm, program, phase, login, server, starting_balance,"
            " reference_balance, currency, status) VALUES ('A', 'F', 'P', 'phase_1', 1, 'S',"
            " 10000, 10000, 'USD', 'active')"
        )
    )
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO trades (account_id, position_id, symbol, broker_symbol, direction,"
            " open_time, close_time, entry_price, volume, net_pnl, status) VALUES (1, 7,"
            " 'XAUUSD', 'XAUUSD', 'buy', '2026-11-11T08:00Z', '2026-11-11T09:00Z', 2650, 0.1,"
            " -50, 'needs_description')"
        )
    )


def test_upgrade_keeps_existing_trades_counted_and_downgrade_drops(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), BEFORE)
    with db_engine.begin() as conn:
        _insert_trade(conn)

    command.upgrade(alembic_config(), "head")

    with db_engine.connect() as conn:
        row = conn.execute(
            text("SELECT excluded_from_stats, excluded_reason, excluded_at FROM trades")
        ).one()
    assert tuple(row) == (False, None, None)
    assert "trade_stats_exclusions" in inspect(db_engine).get_table_names()

    command.downgrade(alembic_config(), BEFORE)

    columns = {c["name"] for c in inspect(db_engine).get_columns("trades")}
    assert not columns & {"excluded_from_stats", "excluded_reason", "excluded_at"}
    assert "trade_stats_exclusions" not in inspect(db_engine).get_table_names()

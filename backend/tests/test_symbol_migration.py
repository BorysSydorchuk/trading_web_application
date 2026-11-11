"""M5-08 migration: broker / canonical symbol columns, backfilled from `symbol`.

Adds trades.broker_symbol, symbol_specs.canonical_symbol and
calculator_margin_requests.broker_symbol (VARCHAR(50) NOT NULL). The migration only copies
`symbol`; the symbols.yaml map is applied later by the worker (DECISIONS 2026-11-10).
Model/migration drift, the roundtrip and the single head are covered by test_migrations.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine.interfaces import ReflectedColumn

from tests.conftest import alembic_config

# Head before M5-08 (drop margin samples and signature).
BEFORE = "80ae699b47ce"
THIS = "5d2e8b1c4a90"
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
NEW_COLUMNS = {
    "trades": "broker_symbol",
    "symbol_specs": "canonical_symbol",
    "calculator_margin_requests": "broker_symbol",
}


def _column(engine: Engine, table: str, name: str) -> ReflectedColumn | None:
    return next((c for c in inspect(engine).get_columns(table) if c["name"] == name), None)


def test_new_revision_follows_80ae699b47ce() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    revision = script.get_revision(THIS)  # no longer the head since M5-09 (test_fx_migration.py)
    assert revision is not None
    assert revision.down_revision == BEFORE


def test_head_has_not_null_varchar50_columns(db_engine: Engine) -> None:
    for table, name in NEW_COLUMNS.items():
        column = _column(db_engine, table, name)
        assert column is not None, f"{table}.{name}"
        assert column["nullable"] is False, f"{table}.{name}"
        assert getattr(column["type"], "length", None) == 50, f"{table}.{name}"


def _insert_old_rows(engine: Engine) -> int:
    """Rows as the dev DB holds them at 80ae699b47ce: GER30 trade/spec, EURUSD request."""
    with engine.begin() as conn:
        account_id: int = conn.execute(
            text(
                "INSERT INTO accounts (name, firm, program, phase, login, server, "
                "starting_balance, currency) VALUES ('M5-08 migration', 'FundedNext', "
                "'Stellar 2-Step', 'phase_1', 987654330, 'FundedNext-Server', 100000, 'USD') "
                "RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO trades (account_id, position_id, symbol, direction, open_time, "
                "close_time, entry_price, volume) VALUES "
                "(:id, 1, 'GER30', 'buy', :now, :later, 24000, 1), "
                "(:id, 2, 'EURUSD', 'sell', :now, :later, 1.16, 0.5)"
            ),
            {"id": account_id, "now": NOW, "later": NOW + timedelta(minutes=30)},
        )
        conn.execute(
            text(
                "INSERT INTO symbol_specs (account_id, symbol, contract_size, tick_size, "
                "tick_value, volume_min, volume_step, volume_max, digits, currency_profit, "
                "currency_margin, synced_at) VALUES (:id, 'GER30', 1, 0.01, 0.0116, 0.1, 0.1, "
                "100, 2, 'EUR', 'EUR', :now)"
            ),
            {"id": account_id, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO calculator_margin_requests (account_id, symbol, direction, volume, "
                "entry, currency, status, created_at, expires_at) VALUES (:id, 'EURUSD', "
                "'buy', 0.5, 1.1, 'USD', 'pending', :now, :expires)"
            ),
            {"id": account_id, "now": NOW, "expires": NOW + timedelta(minutes=1)},
        )
    return account_id


def _values(engine: Engine, account_id: int) -> dict[str, list[tuple[object, ...]]]:
    with engine.connect() as conn:
        return {
            "trades": [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT symbol, broker_symbol FROM trades WHERE account_id=:id "
                        "ORDER BY position_id"
                    ),
                    {"id": account_id},
                )
            ],
            "specs": [
                tuple(r)
                for r in conn.execute(
                    text("SELECT symbol, canonical_symbol FROM symbol_specs WHERE account_id=:id"),
                    {"id": account_id},
                )
            ],
            "requests": [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT symbol, broker_symbol FROM calculator_margin_requests "
                        "WHERE account_id=:id"
                    ),
                    {"id": account_id},
                )
            ],
        }


def test_upgrade_backfills_from_symbol_and_downgrade_restores(db_engine: Engine) -> None:
    cfg = alembic_config()
    account_id: int | None = None
    try:
        command.downgrade(cfg, BEFORE)
        for table, name in NEW_COLUMNS.items():
            assert _column(db_engine, table, name) is None, f"{table}.{name}"
        account_id = _insert_old_rows(db_engine)

        command.upgrade(cfg, "head")

        # Copies only: no GER30 -> GER40 mapping inside the migration.
        assert _values(db_engine, account_id) == {
            "trades": [("GER30", "GER30"), ("EURUSD", "EURUSD")],
            "specs": [("GER30", "GER30")],
            "requests": [("EURUSD", "EURUSD")],
        }

        command.downgrade(cfg, BEFORE)
        for table, name in NEW_COLUMNS.items():
            assert _column(db_engine, table, name) is None, f"{table}.{name}"
        with db_engine.connect() as conn:
            symbols = conn.execute(
                text("SELECT symbol FROM trades WHERE account_id=:id ORDER BY position_id"),
                {"id": account_id},
            ).scalars()
            assert list(symbols) == ["GER30", "EURUSD"]
            assert (
                conn.execute(
                    text("SELECT count(*) FROM symbol_specs WHERE account_id=:id"),
                    {"id": account_id},
                ).scalar_one()
                == 1
            )
    finally:
        try:
            if account_id is not None:
                with db_engine.begin() as conn:
                    for table in ("calculator_margin_requests", "symbol_specs", "trades"):
                        conn.execute(
                            text(f"DELETE FROM {table} WHERE account_id=:id"),  # noqa: S608
                            {"id": account_id},
                        )
                    conn.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": account_id})
        finally:
            command.upgrade(cfg, "head")


def test_downgrade_puts_the_broker_name_back_into_symbol(db_engine: Engine) -> None:
    """Before M5-08 `symbol` held the broker name: a downgrade after the worker mapped rows
    (symbol GER40, broker GER30) restores `symbol` = broker name for trades and requests."""
    cfg = alembic_config()
    account_id: int | None = None
    try:
        command.downgrade(cfg, BEFORE)
        account_id = _insert_old_rows(db_engine)
        command.upgrade(cfg, "head")
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE trades SET symbol='GER40' WHERE account_id=:id AND position_id=1"),
                {"id": account_id},
            )
            conn.execute(
                text(
                    "UPDATE calculator_margin_requests SET symbol='EURUSD-canonical', "
                    "broker_symbol='EURUSD' WHERE account_id=:id"
                ),
                {"id": account_id},
            )
        command.downgrade(cfg, BEFORE)
        with db_engine.connect() as conn:
            trade = conn.execute(
                text("SELECT symbol FROM trades WHERE account_id=:id AND position_id=1"),
                {"id": account_id},
            ).scalar_one()
            request = conn.execute(
                text("SELECT symbol FROM calculator_margin_requests WHERE account_id=:id"),
                {"id": account_id},
            ).scalar_one()
        assert (trade, request) == ("GER30", "EURUSD")
    finally:
        try:
            if account_id is not None:
                with db_engine.begin() as conn:
                    for table in ("calculator_margin_requests", "symbol_specs", "trades"):
                        conn.execute(
                            text(f"DELETE FROM {table} WHERE account_id=:id"),  # noqa: S608
                            {"id": account_id},
                        )
                    conn.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": account_id})
        finally:
            command.upgrade(cfg, "head")

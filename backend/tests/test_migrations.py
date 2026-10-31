"""Migrations apply cleanly both ways and never drift from the ORM models."""

from __future__ import annotations

import re
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Engine, Table, inspect

from app.models import Base
from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "accounts",
    "symbol_specs",
    "trades",
    "trade_exit_deals",
    "chart_links",
    "audio_notes",
    "bias_entries",
    "digests",
    "rule_violations",
    "sync_log",
}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_upgrade_downgrade_upgrade_roundtrip(db_engine: Engine) -> None:
    cfg = alembic_config()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert _current_revision(db_engine) == head  # conftest already upgraded to head
    assert _tables(db_engine) == EXPECTED_TABLES

    command.downgrade(cfg, "base")
    assert _tables(db_engine) == set()
    assert _current_revision(db_engine) is None

    command.upgrade(cfg, "head")
    assert _tables(db_engine) == EXPECTED_TABLES
    assert _current_revision(db_engine) == head


def test_models_match_migrations(db_engine: Engine) -> None:
    """Autogenerate against the migrated DB must find nothing: models and migrations agree."""
    with db_engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        diff: list[Any] = compare_metadata(context, Base.metadata)
    assert diff == []


def test_single_head() -> None:
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


_QUOTED = re.compile(r"'([^']*)'")
_NUMBER = re.compile(r"\b\d+\b")
_WORD = re.compile(r"[a-z_][a-z0-9_]*")


def _check_signature(sql: str, table: Table) -> tuple[list[str], list[str], list[str]]:
    """Normalize a CHECK expression so model text and Postgres' rewritten text compare equal.

    Postgres rewrites `x IN ('a','b')` to `x::text = ANY (ARRAY['a'::varchar, ...])` and
    `BETWEEN` to `>= AND <=`, so compare what matters: string literals (enum values),
    numeric bounds and referenced columns.
    """
    without_literals = _QUOTED.sub("", sql)
    literals = sorted(set(_QUOTED.findall(sql)))
    numbers = sorted(set(_NUMBER.findall(without_literals)))
    columns = sorted(set(_WORD.findall(without_literals)) & set(table.columns.keys()))
    return literals, numbers, columns


def check_constraint_diff(engine: Engine) -> list[str]:
    """Differences between CHECK constraints in the models and in the DB (empty = in sync)."""
    inspector = inspect(engine)
    problems: list[str] = []
    for table in Base.metadata.sorted_tables:
        model = {
            str(c.name): _check_signature(str(c.sqltext), table)
            for c in table.constraints
            if isinstance(c, CheckConstraint)
        }
        db = {
            str(c["name"]): _check_signature(c["sqltext"], table)
            for c in inspector.get_check_constraints(table.name)
        }
        for name in sorted(model.keys() - db.keys()):
            problems.append(f"{table.name}: {name} missing in DB")
        for name in sorted(db.keys() - model.keys()):
            problems.append(f"{table.name}: {name} missing in models")
        for name in sorted(model.keys() & db.keys()):
            if model[name] != db[name]:
                problems.append(f"{table.name}: {name} model={model[name]} db={db[name]}")
    return problems


def test_check_constraints_match_migrations(db_engine: Engine) -> None:
    """compare_metadata ignores CHECKs, so enum drift (e.g. a new status) is caught here."""
    assert check_constraint_diff(db_engine) == []

"""Migrations apply cleanly both ways and never drift from the ORM models."""

from __future__ import annotations

import re
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Engine, Table, inspect, text

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
    "bias_notes",
    "digests",
    "rule_violations",
    "sync_log",
    "journal_field_requirements",
    "journal_requirements_state",
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


def test_required_since_migration_seeds_marker_and_downgrades(db_engine: Engine) -> None:
    """M3-07: one marker row (initial fill not done), empty requirements; down drops both."""
    cfg = alembic_config()
    command.downgrade(cfg, "3c9a1e5d7f20")
    assert {"journal_field_requirements", "journal_requirements_state"}.isdisjoint(
        _tables(db_engine)
    )
    command.upgrade(cfg, "head")
    with db_engine.connect() as conn:
        state = conn.execute(text("SELECT id, initial_fill_at FROM journal_requirements_state"))
        assert state.all() == [(1, None)]
        count = conn.execute(text("SELECT count(*) FROM journal_field_requirements"))
        assert count.scalar_one() == 0


_BEFORE_BIAS_NOTES = "7916fe645fdc"
_BIAS_NOTES = "b6d41a9e2c57"
# Entry 1 raw_text + transcript, then entry 2 transcript, joined into the note text.
_JOINED_BIAS_TEXT = "\n\n".join(["gold up", "золото вгору", "дакс вниз"])


def _old_bias_rows(engine: Engine, weekly_day: str = "2026-11-02") -> None:
    """Old-schema rows (before bias_notes): two entries of one pre_ny period, one weekly, audio."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bias_entries (id, kind, period_date, symbol, direction, raw_text, "
                "transcript) VALUES "
                "(1, 'pre_ny', '2026-11-03', 'XAUUSD', 'bullish', :raw, :t1), "
                "(2, 'pre_ny', '2026-11-03', 'GER40', 'bearish', NULL, :t2), "
                "(3, 'weekly', CAST(:weekly AS date), 'EURUSD', 'neutral', NULL, NULL)"
            ),
            {"raw": "gold up", "t1": "золото вгору", "t2": "дакс вниз", "weekly": weekly_day},
        )
        conn.execute(
            text(
                "INSERT INTO audio_notes (bias_entry_id, file_path, mime_type) "
                "VALUES (2, 'audio/2026/11/a.webm', 'audio/webm')"
            )
        )


def _clear_bias_any_revision(engine: Engine) -> None:
    """Delete bias rows and audio, before or after the bias_notes migration."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM audio_notes WHERE trade_id IS NULL"))
        conn.execute(text("DELETE FROM bias_entries"))
        if "bias_notes" in _tables(engine):
            conn.execute(text("DELETE FROM bias_notes"))


def test_bias_notes_migration_moves_existing_rows(db_engine: Engine) -> None:
    cfg = alembic_config()
    command.downgrade(cfg, _BEFORE_BIAS_NOTES)
    try:
        _old_bias_rows(db_engine)
        command.upgrade(cfg, _BIAS_NOTES)
        with db_engine.connect() as conn:
            notes = conn.execute(
                text("SELECT id, kind, period_date::text, raw_text FROM bias_notes ORDER BY kind")
            ).all()
            entries = conn.execute(
                text("SELECT id, bias_note_id FROM bias_entries ORDER BY id")
            ).all()
            audio = conn.execute(
                text("SELECT bias_note_id FROM audio_notes WHERE trade_id IS NULL")
            ).scalar_one()
        pre_ny, weekly = notes
        assert pre_ny[1:] == ("pre_ny", "2026-11-03", _JOINED_BIAS_TEXT)
        assert weekly[1:] == ("weekly", "2026-11-02", None)
        assert entries == [(1, pre_ny[0]), (2, pre_ny[0]), (3, weekly[0])]
        assert audio == pre_ny[0]

        command.downgrade(cfg, _BEFORE_BIAS_NOTES)
        with db_engine.connect() as conn:
            old = conn.execute(
                text("SELECT id, kind, period_date::text, raw_text FROM bias_entries ORDER BY id")
            ).all()
            audio_owner = conn.execute(
                text("SELECT bias_entry_id FROM audio_notes WHERE trade_id IS NULL")
            ).scalar_one()
        assert old == [
            (1, "pre_ny", "2026-11-03", _JOINED_BIAS_TEXT),
            (2, "pre_ny", "2026-11-03", _JOINED_BIAS_TEXT),
            (3, "weekly", "2026-11-02", None),
        ]
        assert audio_owner == 1  # the note's first entry
    finally:
        _clear_bias_any_revision(db_engine)
        command.upgrade(cfg, "head")


def test_bias_notes_migration_refuses_misaligned_weekly(db_engine: Engine) -> None:
    cfg = alembic_config()
    command.downgrade(cfg, _BEFORE_BIAS_NOTES)
    try:
        _old_bias_rows(db_engine, weekly_day="2026-11-04")  # a Wednesday
        with pytest.raises(RuntimeError, match=r"weekly bias rows must be on a Monday.*id=3"):
            command.upgrade(cfg, _BIAS_NOTES)
    finally:
        _clear_bias_any_revision(db_engine)
        command.upgrade(cfg, "head")


def test_bias_notes_downgrade_refuses_note_without_entries(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bias_notes (kind, period_date, raw_text) "
                "VALUES ('pre_ny', '2026-11-03', 'x')"
            )
        )
    try:
        with pytest.raises(RuntimeError, match="have no entries"):
            command.downgrade(alembic_config(), _BEFORE_BIAS_NOTES)
        assert _current_revision(db_engine) == _BIAS_NOTES
    finally:
        _clear_bias_any_revision(db_engine)

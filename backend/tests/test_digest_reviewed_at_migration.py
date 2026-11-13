"""M6-06a migration (RED): ``digests.reviewed_at`` timestamptz NULL, follows a3e7c91d5b20.

Upgrade adds the nullable column and backfills ``reviewed_at = updated_at`` only for digests
with a non-empty what_worked / what_to_fix / focus_next (NULL and '' are empty; ai_summary does
not count). Downgrade drops the column. Drift / roundtrip / single head: test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config

BEFORE = "a3e7c91d5b20"
UPDATED = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE digests RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


def _columns(engine: Engine) -> dict[str, Any]:
    return {str(c["name"]): c for c in inspect(engine).get_columns("digests")}


def _digest(
    conn: Any, day: int, worked: str | None, fix: str | None, focus: str | None, ai: str | None
) -> None:
    conn.execute(
        text(
            "INSERT INTO digests (kind, period_start, period_end, what_worked, what_to_fix, "
            "focus_next, ai_summary, created_at, updated_at) VALUES ('weekly', :s, :s, :w, :f, "
            ":n, :ai, :u, :u)"
        ),
        {"s": f"2026-10-{day:02d}", "w": worked, "f": fix, "n": focus, "ai": ai, "u": UPDATED},
    )


def test_exactly_one_revision_follows_a3e7c91d5b20() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    children = [r for r in script.walk_revisions() if r.down_revision == BEFORE]

    assert len(children) == 1


def test_head_has_a_nullable_timestamptz_reviewed_at(db_engine: Engine) -> None:
    column = _columns(db_engine)["reviewed_at"]

    assert column["nullable"] is True
    assert getattr(column["type"], "timezone", False) is True


def test_upgrade_backfills_reviewed_at_only_for_non_empty_reviews(db_engine: Engine) -> None:
    cfg = alembic_config()
    try:
        command.downgrade(cfg, BEFORE)
        assert "reviewed_at" not in _columns(db_engine)
        with db_engine.begin() as conn:
            _digest(conn, 5, "worked", None, None, None)
            _digest(conn, 12, None, "fix", None, None)
            _digest(conn, 19, None, None, "focus", None)
            _digest(conn, 26, None, None, None, None)
            _digest(conn, 27, "", "", "", None)
            _digest(conn, 28, None, None, None, "only an AI summary")

        command.upgrade(cfg, "head")

        with db_engine.connect() as conn:
            rows = dict(
                conn.execute(
                    text("SELECT extract(day FROM period_start)::int, reviewed_at FROM digests")
                ).all()
            )
        assert rows[5] == rows[12] == rows[19] == UPDATED
        assert (rows[26], rows[27], rows[28]) == (None, None, None)
    finally:
        command.upgrade(cfg, "head")


def test_downgrade_drops_the_column_and_keeps_the_rows(db_engine: Engine) -> None:
    cfg = alembic_config()
    try:
        with db_engine.begin() as conn:
            _digest(conn, 5, "worked", None, None, None)

        command.downgrade(cfg, BEFORE)

        assert "reviewed_at" not in _columns(db_engine)
        with db_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM digests")).scalar_one() == 1
    finally:
        command.upgrade(cfg, "head")
    assert "reviewed_at" in _columns(db_engine)

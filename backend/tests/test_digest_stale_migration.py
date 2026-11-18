"""M8-01b migration: digests.ai_summary_stale_at follows e4a7c2f9b315; existing digests are
not stale. Drift / roundtrip / single head: test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config

BEFORE = "e4a7c2f9b315"


@pytest.fixture(autouse=True)
def _restore_head(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE digests RESTART IDENTITY CASCADE"))
    command.upgrade(alembic_config(), "head")


def test_upgrade_leaves_existing_digests_not_stale_and_downgrade_drops(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), BEFORE)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO digests (kind, period_start, period_end, ai_summary)"
                " VALUES ('weekly', '2026-11-09', '2026-11-15', 'Факт.')"
            )
        )

    command.upgrade(alembic_config(), "head")

    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT ai_summary, ai_summary_stale_at FROM digests")).one()
    assert tuple(row) == ("Факт.", None)

    command.downgrade(alembic_config(), BEFORE)

    columns = {c["name"] for c in inspect(db_engine).get_columns("digests")}
    assert "ai_summary_stale_at" not in columns

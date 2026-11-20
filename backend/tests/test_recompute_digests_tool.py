# ruff: noqa: F811  (pytest fixtures imported from test_trade_exclusion)
"""M8-10b fixes: one-off recompute of every saved digest after the % base change.

Old snapshots (before the shared base) are simulated by editing a stored number; the tool
must restore the current numbers, keep review texts and summary text, mark a saved summary
stale only when numbers changed, roll back on a dry run, and never write before the backup.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.tools import migrate, recompute_digests
from app.tools.recompute_digests import run, take_backup
from tests.test_digest_recompute import MONTH, WEEK, create, stored
from tests.test_trade_exclusion import (  # noqa: F401  (fixtures)
    _clean,
    _now,
    account,
    closed,
    session,
    week,
)

LATER = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)


def _make_old(session: Session, digest_id: int, *, summary: bool) -> None:
    digest = stored(session, digest_id)
    metrics = dict(digest.metrics)
    combined = dict(metrics["combined"])
    combined["metrics"] = {**combined["metrics"], "net_pnl_pct": {"value": "7.2879"}}
    metrics["combined"] = combined
    digest.metrics = metrics
    digest.what_worked = "терпіння"
    digest.ai_summary = "Факт: 3 угоди." if summary else None
    session.commit()


def test_apply_recomputes_old_numbers_keeps_texts_and_marks_summary_stale(
    client: TestClient, session: Session, week: dict[str, object]
) -> None:
    weekly, monthly = create(client, "weekly", WEEK), create(client, "monthly", MONTH)
    fresh = stored(session, weekly["id"]).metrics
    _make_old(session, weekly["id"], summary=True)
    _make_old(session, monthly["id"], summary=False)
    calls: list[str] = []
    out = io.StringIO()

    def backup() -> Path:
        calls.append("b")
        return Path("x.dump")

    result = run(session, apply=True, now=LATER, out=out, backup=backup)

    assert calls == ["b"]
    assert dict(result) == {weekly["id"]: True, monthly["id"]: True}
    w = stored(session, weekly["id"])
    assert w.metrics == fresh
    assert w.what_worked == "терпіння"
    assert w.ai_summary == "Факт: 3 угоди."
    assert w.ai_summary_stale_at == LATER
    assert w.generated_at == LATER
    m = stored(session, monthly["id"])
    assert m.ai_summary_stale_at is None
    assert m.what_worked == "терпіння"
    assert "x.dump" in out.getvalue()


def test_unchanged_numbers_leave_the_summary_fresh(
    client: TestClient, session: Session, week: dict[str, object]
) -> None:
    weekly = create(client, "weekly", WEEK)
    digest = stored(session, weekly["id"])
    digest.ai_summary = "Факт."
    session.commit()

    assert run(session, apply=True, now=LATER, out=io.StringIO()) == [(weekly["id"], False)]
    assert stored(session, weekly["id"]).ai_summary_stale_at is None


def test_dry_run_changes_nothing_and_takes_no_backup(
    client: TestClient, session: Session, week: dict[str, object]
) -> None:
    weekly = create(client, "weekly", WEEK)
    _make_old(session, weekly["id"], summary=True)

    def no_backup() -> Path:
        raise AssertionError("dry run must not back up")

    result = run(session, apply=False, now=LATER, out=io.StringIO(), backup=no_backup)

    assert result == [(weekly["id"], True)]
    digest = stored(session, weekly["id"])
    assert digest.metrics["combined"]["metrics"]["net_pnl_pct"] == {"value": "7.2879"}
    assert digest.ai_summary_stale_at is None


def test_failed_backup_writes_nothing(
    client: TestClient, session: Session, week: dict[str, object]
) -> None:
    weekly = create(client, "weekly", WEEK)
    _make_old(session, weekly["id"], summary=True)

    def broken() -> Path:
        raise migrate.BackupError("pg_dump failed")

    with pytest.raises(migrate.BackupError):
        run(session, apply=True, now=LATER, out=io.StringIO(), backup=broken)
    session.rollback()
    digest = stored(session, weekly["id"])
    assert digest.metrics["combined"]["metrics"]["net_pnl_pct"] == {"value": "7.2879"}


class _Settings:
    def __init__(self, url: str) -> None:
        self.database_url = url
        self.postgres_port = 5432


def test_take_backup_skips_a_test_database_without_confirming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*_: object, **__: object) -> None:
        raise AssertionError("no confirm / dump for a test database")

    monkeypatch.setattr(migrate, "make_backup", never)
    url = "postgresql+psycopg://u:p@localhost:5432/trading_journal_test"
    deps = migrate.Deps(confirm_target=never)
    assert take_backup(_Settings(url), io.StringIO(), deps) is None  # type: ignore[arg-type]


def test_take_backup_confirms_the_target_then_dumps(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def confirm(url: str, port: int) -> None:
        calls.append("confirm")

    def dump(target: migrate.DbTarget, label: str, *_: object, **__: object) -> Path:
        calls.append(f"dump {target.database} {label}")
        return Path("b.dump")

    monkeypatch.setattr(migrate, "make_backup", dump)
    url = "postgresql+psycopg://u:p@localhost:5432/trading_journal"
    deps = migrate.Deps(confirm_target=confirm)
    assert take_backup(_Settings(url), io.StringIO(), deps) == Path("b.dump")  # type: ignore[arg-type]
    assert calls == ["confirm", "dump trading_journal recompute-digests"]


@pytest.mark.parametrize("error", [migrate.MigrateError("bad url"), RuntimeError("docker down")])
def test_main_fails_readably_and_writes_nothing(
    client: TestClient,
    session: Session,
    week: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    weekly = create(client, "weekly", WEEK)
    _make_old(session, weekly["id"], summary=True)
    monkeypatch.setattr(recompute_digests, "setup_logging", lambda *_: Path("x.log"))

    def broken(*_: object) -> Path:
        raise error

    assert recompute_digests.main(["--apply"], backup=broken) == 1
    assert "нічого не змінено" in capsys.readouterr().err
    digest = stored(session, weekly["id"])
    assert digest.metrics["combined"]["metrics"]["net_pnl_pct"] == {"value": "7.2879"}

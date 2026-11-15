"""Persistent daily execution contract, fake dumps only."""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.backups import BackupStore
from app.services.backup_schedule import BackupSchedule, latest_due, next_due

URL = "postgresql+psycopg://u:synthetic@localhost/schedule_test"
NOW = datetime(2026, 11, 14, 17, tzinfo=UTC)  # 18:00 Brussels


def make(tmp_path: Path, *, healthy: bool = True) -> tuple[BackupSchedule, list[datetime]]:
    calls: list[datetime] = []

    def dump(url: str, path: Path) -> None:
        calls.append(NOW)
        path.write_bytes(b"PGDMP synthetic")

    store = BackupStore(tmp_path, dump=dump, verify=lambda path: None)
    return BackupSchedule(store, URL, healthy=lambda: healthy), calls


@pytest.mark.parametrize("instant,expected", [
    ("2026-03-28T17:00:00+00:00", "2026-03-29T16:00:00+00:00"),
    ("2026-10-24T16:00:00+00:00", "2026-10-25T17:00:00+00:00"),
])
def test_next_regular_1800_tracks_both_dst_changes(instant: str, expected: str) -> None:
    assert next_due(datetime.fromisoformat(instant)).isoformat() == expected


def test_latest_due_before_and_at_1800() -> None:
    assert latest_due(NOW - timedelta(seconds=1)) == NOW - timedelta(days=1)
    assert latest_due(NOW) == NOW


def test_restart_and_multi_day_catchup_do_not_replay_or_shift_schedule(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    job.tick(NOW)
    job.tick(NOW)
    restarted = BackupSchedule(job.store, URL, healthy=lambda: True)
    restarted.tick(NOW + timedelta(days=4, hours=-8))  # morning: one catch-up
    assert len(calls) == 2
    restarted.tick(NOW + timedelta(days=4))  # still runs normal 18:00
    assert len(calls) == 3
    status = restarted.status(NOW + timedelta(days=4))
    assert status["state"] == "ok"
    assert status["last_success_at"] is not None
    assert status["overdue"] is False


def test_unhealthy_dependencies_never_dump_then_recover(tmp_path: Path) -> None:
    job, calls = make(tmp_path, healthy=False)
    job.tick(NOW)
    assert not calls
    assert job.status(NOW)["error_code"] == "dependencies_unhealthy"
    healthy = BackupSchedule(job.store, URL, healthy=lambda: True)
    healthy.tick(NOW + timedelta(minutes=1))
    assert len(calls) == 1
    assert healthy.status(NOW + timedelta(minutes=1))["state"] == "ok"


def test_bounded_retries_and_failure_recovery_keep_failure_history(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    good_dump = job.store.dump

    def fail(url: str, path: Path) -> None:
        raise OSError("secret MUST NOT LEAK")

    job.store.dump = fail
    job.tick(NOW)
    job.tick(NOW + timedelta(minutes=1))  # backoff
    assert job.status(NOW)["attempts"] == 1
    assert "secret" not in str(job.status(NOW))
    job.store.dump = good_dump
    job.tick(NOW + timedelta(minutes=5))
    status = job.status(NOW + timedelta(minutes=5))
    assert len(calls) == 1
    assert status["state"] == "ok"
    assert status["last_failure_at"] is not None
    assert status["last_error_code"] == "backup_failed"


def test_retry_limit_resets_only_for_next_schedule(tmp_path: Path) -> None:
    job, _ = make(tmp_path)

    def fail(url: str, path: Path) -> None:
        raise OSError("synthetic failure")

    job.store.dump = fail
    for minute in (0, 5, 10, 15, 20):
        job.tick(NOW + timedelta(minutes=minute))
    assert job.status(NOW)["attempts"] == 3
    job.tick(NOW + timedelta(days=1))
    assert job.status(NOW + timedelta(days=1))["attempts"] == 1


def test_two_instances_cannot_overlap(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = job.store.dump

    def blocking(url: str, path: Path) -> None:
        entered.set()
        assert release.wait(5)
        original(url, path)

    job.store.dump = blocking
    thread = threading.Thread(target=job.tick, args=(NOW,))
    thread.start()
    try:
        assert entered.wait(5)
        BackupSchedule(job.store, URL, healthy=lambda: True).tick(NOW)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert len(calls) == 1


@pytest.mark.parametrize("published", [True, False])
def test_process_crash_reconciles_published_or_fails_closed(tmp_path: Path, published: bool) -> None:
    job, calls = make(tmp_path)
    create = job.store.create

    def crash(*args: object, **kwargs: object) -> object:
        if published:
            create(URL, now=NOW)
        raise KeyboardInterrupt

    job.store.create = crash  # type: ignore[method-assign,assignment]
    with pytest.raises(KeyboardInterrupt):
        job.tick(NOW)
    job.store.create = create  # type: ignore[method-assign]
    restarted = BackupSchedule(job.store, URL, healthy=lambda: True)
    restarted.tick(NOW + timedelta(minutes=1))
    assert len(calls) == int(published)
    assert restarted.status(NOW)["state"] == ("ok" if published else "failed")
    if not published:
        assert restarted.status(NOW)["error_code"] == "interrupted"


def test_corrupt_state_is_visible_and_never_runs_backup(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    job.tick(NOW)
    job.state_path.write_text("{broken", encoding="utf-8")
    job.tick(NOW + timedelta(days=1))
    assert len(calls) == 1
    assert job.status(NOW)["error_code"] == "state_unavailable"

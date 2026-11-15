"""Persistent daily execution contract, fake dumps only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.backup_schedule import BackupSchedule, latest_due, next_due
from app.services.backup_state import ScheduleState, read_state, schedule_lock, write_state
from app.services.backups import BackupStore, Kind

URL = "postgresql+psycopg://u:synthetic@localhost/schedule_test"
NOW = datetime(2026, 11, 14, 17, tzinfo=UTC)  # 18:00 Brussels


def make(tmp_path: Path, *, healthy: bool = True) -> tuple[BackupSchedule, list[datetime]]:
    calls: list[datetime] = []

    def dump(url: str, path: Path) -> None:
        calls.append(NOW)
        path.write_bytes(b"PGDMP synthetic")

    store = BackupStore(tmp_path, dump=dump, verify=lambda path: None)
    return BackupSchedule(store, URL, healthy=lambda: healthy), calls


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2026-03-28T17:00:00+00:00", "2026-03-29T16:00:00+00:00"),
        ("2026-10-24T16:00:00+00:00", "2026-10-25T17:00:00+00:00"),
    ],
)
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
def test_process_crash_reconciles_published_or_fails_closed(
    tmp_path: Path, published: bool
) -> None:
    job, calls = make(tmp_path)
    create = job.store.create

    def crash(
        url: str,
        *,
        kind: Kind = "daily",
        now: datetime | None = None,
        archive_name: str | None = None,
    ) -> object:
        if published:
            create(url, kind=kind, now=now, archive_name=archive_name)
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


def test_retention_failure_remains_visible_without_duplicate_dump(tmp_path: Path) -> None:
    job, calls = make(tmp_path)

    def fail(url: str) -> list[Path]:
        raise OSError("secret")

    job.store.prune = fail  # type: ignore[method-assign]
    job.tick(NOW)
    job.tick(NOW + timedelta(minutes=1))
    assert len(calls) == 1
    assert job.status(NOW)["error_code"] == "retention_failed"


def test_completed_state_does_not_rehash_archives_on_every_poll(tmp_path: Path) -> None:
    job, _ = make(tmp_path)
    job.tick(NOW)
    job.store._read = lambda *a: pytest.fail("unnecessary archive scan")  # type: ignore[method-assign]
    job.tick(NOW + timedelta(seconds=15))
    assert job.status(NOW)["state"] == "ok"


@pytest.mark.parametrize("state_text", ["{}", '{"version": 2}', "[]", "null"])
def test_incomplete_state_fails_closed(tmp_path: Path, state_text: str) -> None:
    job, calls = make(tmp_path)
    job.tick(NOW)
    job.state_path.write_text(state_text, encoding="utf-8")
    job.tick(NOW + timedelta(days=1))
    assert len(calls) == 1
    assert job.status(NOW)["error_code"] == "state_unavailable"


def test_retry_budget_survives_restarts(tmp_path: Path) -> None:
    job, _ = make(tmp_path)
    count = 0

    def fail(url: str, path: Path) -> None:
        nonlocal count
        count += 1
        raise OSError("secret")

    job.store.dump = fail
    for minute in (0, 5, 10, 15, 20):
        BackupSchedule(job.store, URL, healthy=lambda: True).tick(NOW + timedelta(minutes=minute))
    assert count == 3
    assert job.status(NOW)["failed_attempts"] == 3


def test_interrupted_unpublished_claim_recovers_after_backoff(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    create = job.store.create

    def crash(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt

    job.store.create = crash  # type: ignore[method-assign,assignment]
    with pytest.raises(KeyboardInterrupt):
        job.tick(NOW)
    job.store.create = create  # type: ignore[method-assign]
    restarted = BackupSchedule(job.store, URL, healthy=lambda: True)
    restarted.tick(NOW + timedelta(minutes=1))
    restarted.tick(NOW + timedelta(minutes=6))
    assert len(calls) == 1
    assert restarted.status(NOW + timedelta(minutes=6))["state"] == "ok"


def test_status_detects_stopped_worker_even_when_archive_is_current(tmp_path: Path) -> None:
    job, _ = make(tmp_path)
    job.tick(NOW)
    status = job.status(NOW + timedelta(minutes=3))
    assert status["error_code"] == "worker_unavailable"
    assert status["overdue"] is False


@pytest.mark.parametrize("instant", ["2026-03-29T16:00:00+00:00", "2026-10-25T17:00:00+00:00"])
def test_dst_schedule_executes_exactly_once_at_1800(tmp_path: Path, instant: str) -> None:
    now = datetime.fromisoformat(instant)
    job, calls = make(tmp_path)
    job.tick(now - timedelta(seconds=1))
    job.tick(now)
    BackupSchedule(job.store, URL, healthy=lambda: True).tick(now + timedelta(seconds=1))
    assert len(calls) == 2  # one yesterday catch-up, one current schedule


def test_success_write_failure_recovers_exact_archive_not_an_unrelated_manual_daily(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, calls = make(tmp_path)
    original = job._save

    def save(state: ScheduleState) -> None:
        if state.last_success_at is not None:
            raise OSError("disk full")
        original(state)

    monkeypatch.setattr(job, "_save", save)
    job.tick(NOW)
    assert read_state(job.state_path).running
    restarted = BackupSchedule(job.store, URL, healthy=lambda: True)
    restarted.tick(NOW + timedelta(seconds=15))
    assert len(calls) == 1
    assert restarted.status(NOW)["state"] == "ok"


def test_hard_exit_releases_kernel_lock(tmp_path: Path) -> None:
    lock = tmp_path / "process.lock"
    script = (
        "import os,sys; from pathlib import Path; "
        "from app.services.backup_state import schedule_lock; "
        "ctx=schedule_lock(Path(sys.argv[1])); assert ctx.__enter__(); os._exit(0)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    result = subprocess.run(  # noqa: S603 - fixed synthetic subprocess
        [sys.executable, "-c", script, str(lock)],
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    with schedule_lock(lock) as acquired:
        assert acquired


def test_invalid_claim_fields_fail_closed(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    job.tick(NOW)
    state = json.loads(job.state_path.read_text(encoding="utf-8"))
    state.update(running=True, archive_name=None, started_at=None)
    job.state_path.write_text(json.dumps(state), encoding="utf-8")
    job.tick(NOW + timedelta(days=1))
    assert len(calls) == 1
    assert job.status(NOW)["error_code"] == "state_unavailable"


def test_atomic_state_replace_failure_keeps_previous_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, _ = make(tmp_path)
    job.tick(NOW)
    before = job.state_path.read_bytes()
    state = read_state(job.state_path)
    state.failed_attempts = 99

    def fail_replace(*args: object) -> None:
        raise OSError("synthetic disk error")

    monkeypatch.setattr("app.services.backup_state.os.replace", fail_replace)
    with pytest.raises(OSError, match="synthetic disk error"):
        write_state(job.state_path, state)
    assert job.state_path.read_bytes() == before


def test_damaged_published_archive_is_visible_without_redump(tmp_path: Path) -> None:
    job, calls = make(tmp_path)
    job.tick(NOW)
    state = read_state(job.state_path)
    state.running = True
    state.completed_due_at = None
    state.last_success_at = None
    write_state(job.state_path, state)
    archive = next((job.store.scope(URL) / "daily").glob("*/archive.dump"))
    archive.write_bytes(b"damaged")
    job.tick(NOW + timedelta(minutes=1))
    job.tick(NOW + timedelta(minutes=2))
    assert len(calls) == 1
    assert job.status(NOW)["error_code"] == "archive_invalid"
    assert job.status(NOW)["failed_attempts"] == 1


def test_legacy_dump_lock_fails_visibly_then_recovers_when_owner_resolves_it(
    tmp_path: Path,
) -> None:
    job, calls = make(tmp_path)
    lock = job.store.scope(URL) / ".lock"
    lock.parent.mkdir(parents=True)
    lock.touch()
    job.tick(NOW)
    assert not calls
    assert job.status(NOW)["error_code"] == "backup_locked"
    assert lock.exists()
    lock.unlink()  # Synthetic owner's explicit inspection/resolution, never production auto-unlock.
    job.tick(NOW + timedelta(minutes=5))
    assert len(calls) == 1
    assert job.status(NOW + timedelta(minutes=5))["state"] == "ok"


def test_process_lock_contends_across_processes(tmp_path: Path) -> None:
    lock = tmp_path / "process.lock"
    script = (
        "import sys; from pathlib import Path; "
        "from app.services.backup_state import schedule_lock; "
        "ctx=schedule_lock(Path(sys.argv[1])); acquired=ctx.__enter__(); "
        "ctx.__exit__(None,None,None); sys.exit(1 if acquired else 0)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    with schedule_lock(lock) as acquired:
        assert acquired
        result = subprocess.run(  # noqa: S603 - fixed synthetic subprocess
            [sys.executable, "-c", script, str(lock)],
            env=env,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0


def test_hard_exit_after_publication_reconciles_without_another_dump(tmp_path: Path) -> None:
    script = """
import os, sys
from datetime import datetime
from pathlib import Path
from app.services.backups import BackupStore
from app.services.backup_schedule import BackupSchedule
def dump(url, path):
    path.write_bytes(b'synthetic subprocess archive')
job = BackupSchedule(BackupStore(Path(sys.argv[1]), dump=dump, verify=lambda p: None),
                     sys.argv[2], healthy=lambda: True)
job._success = lambda *args: os._exit(17)
job.tick(datetime.fromisoformat(sys.argv[3]))
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    result = subprocess.run(  # noqa: S603 - fixed script and synthetic database URL
        [sys.executable, "-c", script, str(tmp_path), URL, NOW.isoformat()],
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 17
    restarted, calls = make(tmp_path)
    assert read_state(restarted.state_path).running
    restarted.tick(NOW + timedelta(seconds=15))
    assert not calls
    assert restarted.status(NOW)["state"] == "ok"
    assert len(restarted.store.verified(URL)) == 1

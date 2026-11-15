"""Operational health gate and independent backup executor."""

import threading
from datetime import datetime
from unittest.mock import Mock

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.services.backups import target_key
from app.worker.backup_job import BACKUP_JOB_ID, operational
from app.worker.main import build_scheduler


@pytest.mark.parametrize(
    ("db_ok", "status", "scope", "expected"),
    [
        (True, "ok", True, True),
        (False, "degraded", True, False),
        (True, "ok", False, False),
        (True, "degraded", True, False),
    ],
)
def test_operational_requires_healthy_api_and_matching_database(
    settings: Settings,
    db_ok: bool,
    status: str,
    scope: bool,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Mock(status=200)
    import json

    response.read.return_value = json.dumps(
        {
            "status": status,
            "db": {"ok": db_ok},
            "backup_target": target_key(settings.database_url) if scope else "wrong",
        }
    ).encode()
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr("app.worker.backup_job.HTTPConnection", Mock(return_value=connection))
    assert operational(settings) is expected
    connection.close.assert_called_once()


def test_missing_api_prevents_backup(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.worker.backup_job.HTTPConnection", Mock(side_effect=OSError("secret")))
    assert operational(settings) is False


def test_backup_has_separate_executor_and_immediate_catchup(settings: Settings) -> None:
    callback = Mock()
    scheduler = build_scheduler(settings, backup_job=callback)
    job = scheduler.get_job(BACKUP_JOB_ID)
    assert job.executor == "backups"
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.next_run_time is not None
    assert scheduler.get_job("mt5_sync").executor == "default"
    job.func()
    callback.assert_called_once()


def test_bad_backup_config_does_not_crash_worker(settings: Settings) -> None:
    from app.config import REPO_ROOT

    scheduler = build_scheduler(settings.model_copy(update={"backup_dir": REPO_ROOT / "config"}))
    scheduler.get_job(BACKUP_JOB_ID).func()


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2026-03-28T17:00:01+00:00", "2026-03-29T18:00:00+02:00"),
        ("2026-10-24T16:00:01+00:00", "2026-10-25T18:00:00+01:00"),
    ],
)
def test_daily_cron_follows_brussels_dst(settings: Settings, instant: str, expected: str) -> None:
    scheduler = build_scheduler(settings, backup_job=lambda: None)
    job = scheduler.get_job(BACKUP_JOB_ID)
    assert isinstance(job.trigger, CronTrigger)
    assert (
        job.trigger.get_next_fire_time(None, datetime.fromisoformat(instant)).isoformat()
        == expected
    )


def test_running_backup_does_not_block_sync_executor(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release, synced = threading.Event(), threading.Event(), threading.Event()

    def backup() -> None:
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr("app.worker.main.heartbeat", lambda engine: True)
    scheduler = build_scheduler(
        settings,
        backup_job=backup,
        sync_job=synced.set,
        margin_job=lambda: None,
        warmup_job=lambda: None,
        warmup_daily_job=lambda: None,
        transcription_job=lambda: None,
        requirements_job=lambda: None,
    )
    try:
        scheduler.start()
        assert entered.wait(3)
        assert synced.wait(3)
        assert not release.is_set()
    finally:
        release.set()
        scheduler.shutdown(wait=True)

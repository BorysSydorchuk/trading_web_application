"""Worker skeleton: scheduler wiring and heartbeat behaviour (no real scheduler start)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.services.ai.warmup import WARMUP_DAILY_JOB_ID, WARMUP_JOB_ID, WarmupJob
from app.worker.main import (
    HEARTBEAT_JOB_ID,
    REQUIREMENTS_JOB_ID,
    build_scheduler,
    heartbeat,
)
from app.worker.sync_job import SYNC_JOB_ID
from app.worker.transcription_job import TRANSCRIPTION_JOB_ID


class _BrokenEngine:
    """Stands in for an Engine whose connect() fails like a down Postgres."""

    def connect(self) -> None:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))


def _broken_engine() -> Engine:
    return _BrokenEngine()  # type: ignore[return-value]


def test_build_scheduler_registers_heartbeat(settings: Settings) -> None:
    scheduler = build_scheduler(settings, engine_getter=_broken_engine)

    assert isinstance(scheduler, BackgroundScheduler)
    assert not scheduler.running
    job = scheduler.get_job(HEARTBEAT_JOB_ID)
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(seconds=60)
    assert str(scheduler.timezone) == str(UTC)
    assert [j.id for j in scheduler.get_jobs()] == [
        HEARTBEAT_JOB_ID,
        SYNC_JOB_ID,
        WARMUP_JOB_ID,
        WARMUP_DAILY_JOB_ID,
        TRANSCRIPTION_JOB_ID,
        REQUIREMENTS_JOB_ID,
    ]
    sync = scheduler.get_job(SYNC_JOB_ID)
    assert sync is not None
    assert isinstance(sync.trigger, IntervalTrigger)
    assert sync.trigger.interval == timedelta(seconds=60)
    warmup = scheduler.get_job(WARMUP_JOB_ID)
    assert warmup is not None
    assert isinstance(warmup.trigger, IntervalTrigger)
    assert warmup.trigger.interval == timedelta(seconds=60)
    assert warmup.max_instances == 1
    transcription = scheduler.get_job(TRANSCRIPTION_JOB_ID)
    assert transcription is not None
    assert isinstance(transcription.trigger, IntervalTrigger)
    assert transcription.trigger.interval == timedelta(seconds=2)
    assert transcription.max_instances == 1
    assert transcription.coalesce is True
    requirements = scheduler.get_job(REQUIREMENTS_JOB_ID)
    assert requirements is not None
    assert isinstance(requirements.trigger, IntervalTrigger)
    assert requirements.trigger.interval == timedelta(seconds=60)


def test_sync_job_errors_are_contained(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    def exploding_sync() -> None:
        raise RuntimeError("sync boom")

    scheduler = build_scheduler(settings, engine_getter=_broken_engine, sync_job=exploding_sync)
    job = scheduler.get_job(SYNC_JOB_ID)
    assert job is not None
    job.func()  # must not raise
    assert "Job 'mt5_sync' failed" in caplog.text


def test_heartbeat_logs_when_db_ok(db_engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.worker.main")

    assert heartbeat(lambda: db_engine) is True
    assert "Heartbeat: worker alive, database ok" in caplog.text


def test_heartbeat_swallows_db_failure(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.worker.main")

    assert heartbeat(_broken_engine) is False  # no exception escapes
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "database is unreachable (ConnectionRefusedError)" in errors[0].getMessage()


def test_scheduled_job_never_raises(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    """Even an unexpected error inside a job is logged, not propagated to the scheduler."""

    def _exploding_engine() -> Engine:
        raise RuntimeError("boom")

    scheduler = build_scheduler(settings, engine_getter=_exploding_engine)
    job = scheduler.get_job(HEARTBEAT_JOB_ID)
    assert job is not None

    job.func()  # must not raise

    assert "Job 'heartbeat' failed" in caplog.text
    assert "RuntimeError: boom" in caplog.text


def test_warmup_job_errors_are_contained(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    def exploding_warmup() -> None:
        raise RuntimeError("warm-up boom")

    scheduler = build_scheduler(settings, engine_getter=_broken_engine, warmup_job=exploding_warmup)
    job = scheduler.get_job(WARMUP_JOB_ID)
    assert job is not None
    job.func()  # must not raise
    assert "Job 'ai_warmup' failed" in caplog.text


def test_transcription_job_errors_are_contained(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    def exploding() -> None:
        raise RuntimeError("whisper boom")

    scheduler = build_scheduler(settings, engine_getter=_broken_engine, transcription_job=exploding)
    job = scheduler.get_job(TRANSCRIPTION_JOB_ID)
    assert job is not None
    job.func()  # must not raise
    assert "Job 'transcription' failed" in caplog.text


def test_skip_noise_filter_only_hides_transcription_skips() -> None:
    from app.worker.main import _SkipNoiseFilter

    def record(job_name: str) -> logging.LogRecord:
        return logging.LogRecord(
            "apscheduler.scheduler",
            logging.WARNING,
            __file__,
            1,
            'Execution of job "%s" skipped: maximum number of running instances reached (1)',
            (job_name,),
            None,
        )

    noise = _SkipNoiseFilter()
    assert noise.filter(record("transcription (trigger: interval[0:00:02])")) is False
    assert noise.filter(record("mt5_sync (trigger: interval[0:01:00])")) is True


def test_default_transcription_job_uses_whisper_lazily(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path
    from typing import Any

    from app.worker import main as worker_main

    calls: list[tuple[Any, Path]] = []

    def fake_cycle(_factory: Any, transcriber: Any, data_dir: Path) -> None:
        calls.append((transcriber, data_dir))

    monkeypatch.setattr(worker_main, "run_transcription_cycle", fake_cycle)
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: None)
    job = worker_main.default_transcription_job(settings)
    job()
    job()
    assert len(calls) == 2
    assert calls[0][0] is calls[1][0]  # one transcriber per process
    assert calls[0][0].options.model == settings.whisper_model
    assert calls[0][1] == settings.data_dir


# --- ai_warmup_daily (Mon-Fri 07:30 Europe/Brussels) ---

BRUSSELS = ZoneInfo("Europe/Brussels")


def _bxl(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BRUSSELS)


def _daily_trigger(settings: Settings) -> CronTrigger:
    scheduler = build_scheduler(settings, engine_getter=_broken_engine)
    job = scheduler.get_job(WARMUP_DAILY_JOB_ID)
    assert job is not None
    assert job.coalesce is True
    assert job.misfire_grace_time == 1800  # asleep longer at 07:30: skipped, never late
    assert isinstance(job.trigger, CronTrigger)
    return job.trigger


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        # Monday 06:00 -> Monday 07:30 Brussels (winter: 06:30 UTC)
        (_bxl(2026, 11, 9, 6, 0), _bxl(2026, 11, 9, 7, 30)),
        # Monday 08:00 -> Tuesday 07:30
        (_bxl(2026, 11, 9, 8, 0), _bxl(2026, 11, 10, 7, 30)),
        # Friday 08:00 -> Monday (no Saturday / Sunday)
        (_bxl(2026, 11, 13, 8, 0), _bxl(2026, 11, 16, 7, 30)),
        # Saturday 06:00 -> Monday
        (_bxl(2026, 11, 14, 6, 0), _bxl(2026, 11, 16, 7, 30)),
        # summer time (CEST) still 07:30 local
        (_bxl(2027, 6, 7, 6, 0), _bxl(2027, 6, 7, 7, 30)),
    ],
)
def test_daily_warmup_fires_weekdays_at_0730_brussels(
    settings: Settings, after: datetime, expected: datetime
) -> None:
    fire = _daily_trigger(settings).get_next_fire_time(None, after)

    assert fire is not None
    assert fire == expected


def test_daily_job_flags_the_default_warmup_job(settings: Settings) -> None:
    scheduler = build_scheduler(settings, engine_getter=_broken_engine)
    daily = scheduler.get_job(WARMUP_DAILY_JOB_ID)
    warmup = scheduler.get_job(WARMUP_JOB_ID)
    assert daily is not None
    assert warmup is not None
    target = warmup.func.__wrapped__
    assert isinstance(target, WarmupJob)
    assert target._daily_requested_at is None

    daily.func()

    assert target._daily_requested_at is not None

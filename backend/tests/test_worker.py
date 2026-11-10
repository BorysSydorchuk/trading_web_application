"""Worker skeleton: scheduler wiring and heartbeat behaviour (no real scheduler start)."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
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

# app.worker.margin_job.MARGIN_JOB_ID (literal here so the older tests import without it).
MARGIN_JOB_ID = "calculator_margin"


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
        MARGIN_JOB_ID,
        WARMUP_JOB_ID,
        WARMUP_DAILY_JOB_ID,
        TRANSCRIPTION_JOB_ID,
        REQUIREMENTS_JOB_ID,
    ]
    sync = scheduler.get_job(SYNC_JOB_ID)
    assert sync is not None
    assert isinstance(sync.trigger, IntervalTrigger)
    assert sync.trigger.interval == timedelta(seconds=60)
    margin = scheduler.get_job(MARGIN_JOB_ID)
    assert margin is not None
    assert isinstance(margin.trigger, IntervalTrigger)
    assert margin.trigger.interval == timedelta(seconds=2)
    assert margin.max_instances == 1
    assert margin.coalesce is True
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
    assert noise.filter(record("calculator_margin (trigger: interval[0:00:02])")) is False
    assert noise.filter(record("mt5_sync (trigger: interval[0:01:00])")) is True


def test_default_transcription_job_uses_whisper_lazily(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:

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


# --- calculator margin job (M5-04d): shares the sync job's Mt5Source and lock ---


def test_margin_job_id_and_interval() -> None:
    from app.worker import margin_job

    assert margin_job.MARGIN_JOB_ID == MARGIN_JOB_ID
    assert margin_job.MARGIN_JOB_INTERVAL_S == 2


def test_shared_mt5_creates_one_source_lazily_and_has_one_lock() -> None:
    from app.worker.mt5_shared import SharedMt5

    made: list[object] = []

    def factory() -> Any:
        made.append(object())
        return made[-1]

    shared = SharedMt5(factory)
    assert made == []  # nothing created before the first job run
    first = shared.source()
    assert shared.source() is first
    assert made == [first]
    assert isinstance(shared.lock, type(threading.Lock()))
    assert shared.lock is shared.lock


def test_sync_and_margin_jobs_share_one_source_and_one_lock(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import main as worker_main
    from app.worker.mt5_shared import SharedMt5

    created: list[object] = []

    def factory() -> Any:
        created.append(object())
        return created[-1]

    seen: dict[str, tuple[Any, Any]] = {}

    def fake_sync(_factory: Any, source: Any, *, lock: Any, **_: Any) -> list[int]:
        seen["sync"] = (source, lock)
        return []

    def fake_margin(_factory: Any, source: Any, lock: Any, **_: Any) -> None:
        seen["margin"] = (source, lock)

    monkeypatch.setattr(worker_main, "run_sync_cycle", fake_sync)
    monkeypatch.setattr(worker_main, "run_margin_cycle", fake_margin)
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: None)
    shared = SharedMt5(factory)
    scheduler = build_scheduler(settings, engine_getter=_broken_engine, mt5=shared)

    for job_id in (MARGIN_JOB_ID, SYNC_JOB_ID, MARGIN_JOB_ID):
        job = scheduler.get_job(job_id)
        assert job is not None
        job.func.__wrapped__()  # unwrapped: a failure must fail the test, not be logged

    assert len(created) == 1
    assert seen["sync"] == (created[0], shared.lock)
    assert seen["margin"] == (created[0], shared.lock)


def test_build_scheduler_default_shares_the_mt5_source_without_creating_it(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import main as worker_main

    made: list[Any] = []

    def fake_make_source(_settings: Settings) -> Any:
        made.append(object())
        return made[-1]

    monkeypatch.setattr(worker_main, "make_source", fake_make_source)
    seen: list[Any] = []
    monkeypatch.setattr(
        worker_main, "run_sync_cycle", lambda _f, src, **kw: seen.append((src, kw["lock"]))
    )
    monkeypatch.setattr(
        worker_main, "run_margin_cycle", lambda _f, src, lock, **_: seen.append((src, lock))
    )
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: None)

    scheduler = build_scheduler(settings, engine_getter=_broken_engine)
    assert made == []  # building the scheduler never creates an MT5 source

    for job_id in (SYNC_JOB_ID, MARGIN_JOB_ID):
        job = scheduler.get_job(job_id)
        assert job is not None
        job.func.__wrapped__()

    assert len(made) == 1
    assert seen[0] == seen[1]
    assert seen[0][0] is made[0]


def test_margin_job_errors_are_contained(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    def exploding() -> None:
        raise RuntimeError("margin boom")

    scheduler = build_scheduler(settings, engine_getter=_broken_engine, margin_job=exploding)
    job = scheduler.get_job(MARGIN_JOB_ID)
    assert job is not None
    job.func()  # must not raise
    assert "Job 'calculator_margin' failed" in caplog.text


def test_worker_start_fails_interrupted_margin_requests_before_jobs_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.worker import main as worker_main

    order: list[str] = []

    class FakeScheduler:
        running = False

        def start(self) -> None:
            order.append("scheduler.start")
            raise KeyboardInterrupt

    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "setup_logging", lambda *_: tmp_path / "worker.log")
    monkeypatch.setattr(worker_main, "check_config_files", lambda: None)
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: None)
    monkeypatch.setattr(worker_main, "mark_interrupted_runs", lambda _f: order.append("sync"))
    monkeypatch.setattr(worker_main, "reset_interrupted_notes", lambda _f: order.append("notes"))

    def fake_mark_margin(_factory: Any) -> int:
        order.append("margin")
        return 0

    monkeypatch.setattr(worker_main, "mark_interrupted_margin_requests", fake_mark_margin)
    monkeypatch.setattr(worker_main, "_install_signal_handlers", lambda _stop: None)
    monkeypatch.setattr(worker_main, "build_scheduler", lambda *_a, **_k: FakeScheduler())
    monkeypatch.setattr(worker_main, "dispose_engine", lambda: None)

    assert worker_main.main() == 0

    assert "margin" in order
    assert order.index("margin") < order.index("scheduler.start")

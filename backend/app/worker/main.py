"""Worker process: an APScheduler BackgroundScheduler (UTC) running periodic jobs;
the main thread just waits for a stop signal.

Jobs: `heartbeat` (DB check), `mt5_sync` (MT5 -> DB, see `app.worker.sync_job`),
`ai_warmup` (one AI call after an extraction schema change or a quiet day, see
`app.services.ai.warmup`), `ai_warmup_daily` (Mon-Fri 07:30 Brussels cron, flags a warm-up),
`calculator_margin` (live MT5 margin for calculator requests, every 2 s, sharing the sync
job's Mt5Source and lock, see `app.worker.margin_job`),
`transcription` (voice notes -> text, see `app.worker.transcription_job`) and
`journal_requirements` (stamps required_since soon after a journal_fields.yaml change, see
`app.services.journal_requirements`; the API syncs too, on every journal read).
Every job is wrapped by `_safe` so an exception is logged and the scheduler keeps running.
"""

from __future__ import annotations

import functools
import logging
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from types import FrameType
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.config_files import ConfigError, check_config_files, get_journal_fields
from app.db import dispose_engine, get_engine, get_session_factory
from app.domain.sessions import DEFAULT_TZ
from app.logging_setup import setup_logging
from app.mt5.source import Mt5Source
from app.services.ai.warmup import (
    DAILY_DAYS,
    DAILY_GRACE_S,
    DAILY_HOUR,
    DAILY_MINUTE,
    WARMUP_DAILY_JOB_ID,
    WARMUP_JOB_ID,
    WARMUP_JOB_INTERVAL_S,
    WarmupJob,
)
from app.services.journal_requirements import sync_requirements
from app.services.transcriber import Transcriber, WhisperOptions, WhisperTranscriber
from app.worker.margin_job import (
    MARGIN_JOB_ID,
    MARGIN_JOB_INTERVAL_S,
    mark_interrupted_margin_requests,
    run_margin_cycle,
)
from app.worker.mt5_shared import SharedMt5
from app.worker.sync_job import (
    SYNC_JOB_ID,
    SYNC_JOB_INTERVAL_S,
    make_source,
    mark_interrupted_runs,
    run_sync_cycle,
)
from app.worker.transcription_job import (
    TRANSCRIPTION_JOB_ID,
    TRANSCRIPTION_JOB_INTERVAL_S,
    reset_interrupted_notes,
    run_transcription_cycle,
)

logger = logging.getLogger(__name__)

HEARTBEAT_JOB_ID = "heartbeat"
HEARTBEAT_INTERVAL_S = 60
REQUIREMENTS_JOB_ID = "journal_requirements"
REQUIREMENTS_JOB_INTERVAL_S = 60
# How often the main thread wakes while waiting for a stop signal. On Windows, Python only
# runs signal handlers (Ctrl+C, SIGTERM, Ctrl+Break) when the main thread wakes up, so a
# short wait keeps shutdown prompt.
STOP_POLL_S = 1.0


def _safe(job_id: str, func: Callable[[], None]) -> Callable[[], None]:
    """Wrap a job so any exception is logged with its traceback and never escapes."""

    @functools.wraps(func)
    def wrapper() -> None:
        try:
            func()
        except Exception:
            logger.exception("Job %r failed; the worker keeps running", job_id)

    return wrapper


def heartbeat(engine_getter: Callable[[], Engine] = get_engine) -> bool:
    """Log a heartbeat line and check DB reachability. Returns True when the DB answered.

    A DB failure is logged as a readable error and swallowed: the worker must not crash
    because Postgres is down.
    """
    try:
        with engine_getter().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        orig = getattr(exc, "orig", None) or exc
        logger.error(
            "Heartbeat: database is unreachable (%s). Is Postgres running? (`make db-up`)",
            type(orig).__name__,
        )
        logger.debug("Heartbeat DB error details", exc_info=exc)
        return False
    logger.info("Heartbeat: worker alive, database ok")
    return True


def sync_journal_requirements(session_factory: sessionmaker[Session] | None = None) -> None:
    """Sync journal_field_requirements with journal_fields.yaml (one SELECT when nothing
    changed). A broken YAML leaves the table alone (already reported at start, DEBUG)."""
    try:
        config = get_journal_fields()
    except ConfigError:
        logger.debug("journal_requirements: journal_fields.yaml is invalid, table not touched")
        return
    with (session_factory or get_session_factory())() as db:
        sync_requirements(db, config)


def default_mt5(settings: Settings) -> SharedMt5:
    """One MT5 source for the process (created on the first job run) and its lock."""

    def factory() -> Mt5Source:
        return make_source(settings)

    return SharedMt5(factory)


def default_sync_job(mt5: SharedMt5) -> Callable[[], None]:
    """Sync under the shared MT5 lock, DB sessions per account."""

    def job() -> None:
        run_sync_cycle(get_session_factory(), mt5.source(), lock=mt5.lock)

    return job


def default_margin_job(mt5: SharedMt5) -> Callable[[], None]:
    """At most one margin request per run; skipped while sync holds the lock."""

    def job() -> None:
        run_margin_cycle(get_session_factory(), mt5.source(), mt5.lock)

    return job


def default_transcription_job(settings: Settings) -> Callable[[], None]:
    """One Whisper transcriber per process; the model loads on the first note."""
    transcriber: list[Transcriber] = []

    def job() -> None:
        if not transcriber:
            transcriber.append(WhisperTranscriber(WhisperOptions.from_settings(settings)))
        run_transcription_cycle(get_session_factory(), transcriber[0], settings.data_dir)

    return job


def _noop() -> None:
    return None


_QUIET_SKIP_JOBS = (TRANSCRIPTION_JOB_ID, MARGIN_JOB_ID)


class _SkipNoiseFilter(logging.Filter):
    """Drop APScheduler's "skipped: maximum number of running instances" line for the
    2 s jobs: one note can take a minute, one margin lookup a terminal start-up."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            "maximum number of running instances" in message
            and any(job_id in message for job_id in _QUIET_SKIP_JOBS)
        )


def build_scheduler(
    settings: Settings | None = None,
    *,
    engine_getter: Callable[[], Engine] = get_engine,
    sync_job: Callable[[], None] | None = None,
    warmup_job: Callable[[], None] | None = None,
    warmup_daily_job: Callable[[], None] | None = None,
    transcription_job: Callable[[], None] | None = None,
    requirements_job: Callable[[], None] | None = None,
    margin_job: Callable[[], None] | None = None,
    mt5: SharedMt5 | None = None,
) -> BackgroundScheduler:
    """Return a configured (not started) scheduler with all worker jobs registered."""
    settings = settings or get_settings()
    # Sync and margin jobs: one source, one lock.
    shared = mt5 if mt5 is not None else default_mt5(settings)
    scheduler = BackgroundScheduler(
        timezone=UTC,
        job_defaults={
            "coalesce": True,  # after a sleep/hibernate run a missed job once, not N times
            "max_instances": 1,
            "misfire_grace_time": HEARTBEAT_INTERVAL_S,
        },
    )

    def _heartbeat_job() -> None:
        heartbeat(engine_getter)

    scheduler.add_job(
        _safe(HEARTBEAT_JOB_ID, _heartbeat_job),
        trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S, timezone=UTC),
        id=HEARTBEAT_JOB_ID,
        name=HEARTBEAT_JOB_ID,
        next_run_time=datetime.now(UTC),  # first beat right after start
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(SYNC_JOB_ID, sync_job or default_sync_job(shared)),
        trigger=IntervalTrigger(seconds=SYNC_JOB_INTERVAL_S, timezone=UTC),
        id=SYNC_JOB_ID,
        name=SYNC_JOB_ID,
        next_run_time=datetime.now(UTC),  # due accounts sync right after start
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(MARGIN_JOB_ID, margin_job or default_margin_job(shared)),
        trigger=IntervalTrigger(seconds=MARGIN_JOB_INTERVAL_S, timezone=UTC),
        id=MARGIN_JOB_ID,
        name=MARGIN_JOB_ID,
        max_instances=1,  # one MT5 lookup at a time
        coalesce=True,
        replace_existing=True,
    )
    default_warmup = WarmupJob(settings) if warmup_job is None else None
    scheduler.add_job(
        _safe(WARMUP_JOB_ID, warmup_job or default_warmup or _noop),
        trigger=IntervalTrigger(seconds=WARMUP_JOB_INTERVAL_S, timezone=UTC),
        id=WARMUP_JOB_ID,
        name=WARMUP_JOB_ID,
        max_instances=1,  # a warm-up call can take ~25 s; never two at once
        next_run_time=datetime.now(UTC),
        replace_existing=True,
    )
    # Only flags the request; the `ai_warmup` job above makes the call (never two at once).
    daily = warmup_daily_job or (default_warmup.request_daily if default_warmup else _noop)
    scheduler.add_job(
        _safe(WARMUP_DAILY_JOB_ID, daily),
        trigger=CronTrigger(
            day_of_week=DAILY_DAYS,
            hour=DAILY_HOUR,
            minute=DAILY_MINUTE,
            timezone=ZoneInfo(DEFAULT_TZ),
        ),
        id=WARMUP_DAILY_JOB_ID,
        name=WARMUP_DAILY_JOB_ID,
        coalesce=True,
        misfire_grace_time=DAILY_GRACE_S,  # asleep longer at 07:30: skip, never fire late
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(TRANSCRIPTION_JOB_ID, transcription_job or default_transcription_job(settings)),
        trigger=IntervalTrigger(seconds=TRANSCRIPTION_JOB_INTERVAL_S, timezone=UTC),
        id=TRANSCRIPTION_JOB_ID,
        name=TRANSCRIPTION_JOB_ID,
        max_instances=1,  # one note at a time
        coalesce=True,
        next_run_time=datetime.now(UTC),
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(REQUIREMENTS_JOB_ID, requirements_job or sync_journal_requirements),
        trigger=IntervalTrigger(seconds=REQUIREMENTS_JOB_INTERVAL_S, timezone=UTC),
        id=REQUIREMENTS_JOB_ID,
        name=REQUIREMENTS_JOB_ID,
        next_run_time=datetime.now(UTC),
        replace_existing=True,
    )
    return scheduler


def _install_signal_handlers(stop: threading.Event) -> None:
    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received %s, shutting down", signal.Signals(signum).name)
        stop.set()

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break / console close
        signals.append(signal.SIGBREAK)
    for sig in signals:
        signal.signal(sig, _on_signal)


def main() -> int:
    settings = get_settings()
    log_path = setup_logging("worker.log", settings)
    logger.info("Worker starting (env=%s), logging to %s", settings.app_env, log_path)
    # Broken YAML is logged loudly; the jobs retry every cycle. ai_pricing.yaml is checked
    # too: the warm-up job makes AI calls and prices them.
    check_config_files()
    mark_interrupted_runs(get_session_factory())
    # Single worker process assumed: every `processing` margin request was interrupted.
    mark_interrupted_margin_requests(get_session_factory())
    # Single worker process assumed: every `processing` note is re-queued here.
    reset_interrupted_notes(get_session_factory())
    logging.getLogger("apscheduler.scheduler").addFilter(_SkipNoiseFilter())
    stop = threading.Event()
    _install_signal_handlers(stop)
    scheduler = build_scheduler(settings)
    try:
        scheduler.start()
        while not stop.wait(STOP_POLL_S):
            pass
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
    except Exception:
        logger.exception("Worker crashed")
        return 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        dispose_engine()
        logger.info("worker stopped")
    return 0

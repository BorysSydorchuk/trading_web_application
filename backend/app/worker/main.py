"""Worker process: an APScheduler BackgroundScheduler (UTC) running periodic jobs;
the main thread just waits for a stop signal.

Jobs: `heartbeat` (DB check), `mt5_sync` (MT5 -> DB, see `app.worker.sync_job`),
`ai_warmup` (one AI call after an extraction schema change, see `app.services.ai.warmup`)
and `transcription` (voice notes -> text, see `app.worker.transcription_job`).
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

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.config_files import check_config_files
from app.db import dispose_engine, get_engine, get_session_factory
from app.logging_setup import setup_logging
from app.mt5.source import Mt5Source
from app.services.ai.warmup import WARMUP_JOB_ID, WARMUP_JOB_INTERVAL_S, WarmupJob
from app.services.transcriber import Transcriber, WhisperOptions, WhisperTranscriber
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


def default_sync_job(settings: Settings) -> Callable[[], None]:
    """One MT5 source for the process (created on first run), DB sessions per account."""
    source: list[Mt5Source] = []

    def job() -> None:
        if not source:
            source.append(make_source(settings))
        run_sync_cycle(get_session_factory(), source[0])

    return job


def default_transcription_job(settings: Settings) -> Callable[[], None]:
    """One Whisper transcriber per process; the model loads on the first note."""
    transcriber: list[Transcriber] = []

    def job() -> None:
        if not transcriber:
            transcriber.append(WhisperTranscriber(WhisperOptions.from_settings(settings)))
        run_transcription_cycle(get_session_factory(), transcriber[0], settings.data_dir)

    return job


class _SkipNoiseFilter(logging.Filter):
    """Drop APScheduler's "skipped: maximum number of running instances" line for the
    transcription job: it runs every 2 s while one note can take a minute."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            "maximum number of running instances" in message and TRANSCRIPTION_JOB_ID in message
        )


def build_scheduler(
    settings: Settings | None = None,
    *,
    engine_getter: Callable[[], Engine] = get_engine,
    sync_job: Callable[[], None] | None = None,
    warmup_job: Callable[[], None] | None = None,
    transcription_job: Callable[[], None] | None = None,
) -> BackgroundScheduler:
    """Return a configured (not started) scheduler with all worker jobs registered."""
    settings = settings or get_settings()
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
        _safe(SYNC_JOB_ID, sync_job or default_sync_job(settings)),
        trigger=IntervalTrigger(seconds=SYNC_JOB_INTERVAL_S, timezone=UTC),
        id=SYNC_JOB_ID,
        name=SYNC_JOB_ID,
        next_run_time=datetime.now(UTC),  # due accounts sync right after start
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(WARMUP_JOB_ID, warmup_job or WarmupJob(settings)),
        trigger=IntervalTrigger(seconds=WARMUP_JOB_INTERVAL_S, timezone=UTC),
        id=WARMUP_JOB_ID,
        name=WARMUP_JOB_ID,
        max_instances=1,  # a warm-up call can take ~25 s; never two at once
        next_run_time=datetime.now(UTC),
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

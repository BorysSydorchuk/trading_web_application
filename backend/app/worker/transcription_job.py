"""The `transcription` worker job (docs/api.md M3): one voice note per run, oldest first.

Claim: `SELECT ... FOR UPDATE SKIP LOCKED` on the oldest `pending` note, set `processing`,
commit. Transcription then runs outside any transaction; progress and the result are
written in separate short transactions. Every failure ends as `failed` with an error code
(UI) and an English detail (log + `transcription_error`); the job never raises.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import ConfigError, get_transcription
from app.domain.audio import resolve_audio_path
from app.models import AudioNote
from app.models.enums import TranscriptionErrorCode, TranscriptionStatus
from app.services.transcriber import Transcriber, TranscriptionError, TranscriptionRun

logger = logging.getLogger(__name__)

TRANSCRIPTION_JOB_ID = "transcription"
TRANSCRIPTION_JOB_INTERVAL_S = 2
TIMEOUT_S = 600.0  # > 600 s of work -> `timeout`
# A note still `processing` this long after its claim lost its final write -> `timeout`.
STALE_AFTER_S = TIMEOUT_S + 15 * 60
PROGRESS_INTERVAL_S = 1.0  # at most one progress write per second
MAX_ERROR_DETAIL = 2000
_PROGRESS_STEP = Decimal("0.001")
_MAX_RUNNING_PROGRESS = Decimal("0.999")  # 1.0 only when done

Clock = Callable[[], float]
Now = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ClaimedNote:
    id: int
    file_path: str


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    duration: float
    transcribe_s: float  # wall time of decode + transcription (model load excluded)


def claim_next_note(session_factory: sessionmaker[Session], now: Now) -> ClaimedNote | None:
    """Oldest pending note -> processing (committed). None when the queue is empty."""
    with session_factory() as session:
        note = session.scalars(
            select(AudioNote)
            .where(AudioNote.transcription_status == TranscriptionStatus.PENDING.value)
            .order_by(AudioNote.created_at, AudioNote.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if note is None:
            return None
        note.transcription_status = TranscriptionStatus.PROCESSING.value
        note.started_at = now()
        note.progress = Decimal(0)
        claimed = ClaimedNote(id=note.id, file_path=note.file_path)
        session.commit()
    return claimed


def _write(session_factory: sessionmaker[Session], note_id: int, values: dict[str, Any]) -> bool:
    """Update a note that is still `processing`; False when it no longer is."""
    with session_factory() as session:
        result = session.execute(
            update(AudioNote)
            .where(
                AudioNote.id == note_id,
                AudioNote.transcription_status == TranscriptionStatus.PROCESSING.value,
            )
            .values(**values)
        )
        session.commit()
    return bool(getattr(result, "rowcount", 0))


def _duration(seconds: float) -> Decimal:
    return Decimal(str(max(seconds, 0.0))).quantize(_PROGRESS_STEP)


def progress_value(end: float, duration: float) -> Decimal | None:
    """segment end / duration, 3 decimals, kept below 1 while processing."""
    if duration <= 0:
        return None
    ratio = Decimal(str(max(end, 0.0) / duration)).quantize(_PROGRESS_STEP, rounding=ROUND_DOWN)
    return min(ratio, _MAX_RUNNING_PROGRESS)


class _ProgressReporter:
    """Writes progress at most once per PROGRESS_INTERVAL_S; DB errors only log a warning."""

    def __init__(
        self, session_factory: sessionmaker[Session], note_id: int, duration: float, clock: Clock
    ) -> None:
        self._factory = session_factory
        self._note_id = note_id
        self._duration = duration
        self._clock = clock
        self._last = clock()

    def write(self, values: dict[str, Any]) -> None:
        try:
            _write(self._factory, self._note_id, values)
        except SQLAlchemyError as exc:
            logger.warning("Audio note %s: progress not saved (%s)", self._note_id, exc)

    def segment_done(self, end: float) -> None:
        if self._clock() - self._last < PROGRESS_INTERVAL_S:
            return
        value = progress_value(end, self._duration)
        if value is not None:
            self.write({"progress": value})
            self._last = self._clock()


def _audio_path(data_dir: Path, note: ClaimedNote) -> Path:
    path = resolve_audio_path(data_dir, note.file_path)
    if path is None:
        raise TranscriptionError(
            TranscriptionErrorCode.AUDIO_MISSING,
            f"stored path {note.file_path!r} is outside {data_dir / 'audio'}",
        )
    if not path.is_file():
        raise TranscriptionError(TranscriptionErrorCode.AUDIO_MISSING, f"file {path} not found")
    return path


def _collect(run: TranscriptionRun, reporter: _ProgressReporter, clock: Clock, start: float) -> str:
    texts: list[str] = []
    for segment in run.segments:
        texts.append(segment.text.strip())
        elapsed = clock() - start
        if elapsed > TIMEOUT_S:
            raise TranscriptionError(
                TranscriptionErrorCode.TIMEOUT,
                f"stopped after {elapsed:.0f} s at {segment.end:.1f} s of {run.duration:.1f} s",
            )
        reporter.segment_done(segment.end)
    return " ".join(t for t in texts if t).strip()


def transcribe_note(
    session_factory: sessionmaker[Session],
    note: ClaimedNote,
    transcriber: Transcriber,
    data_dir: Path,
    initial_prompt: str | None,
    clock: Clock,
) -> TranscriptResult:
    """Run the transcriber on a claimed note, reporting progress. Raises on failure."""
    path = _audio_path(data_dir, note)
    transcriber.load()
    start = clock()
    run = transcriber.transcribe(path, initial_prompt)
    reporter = _ProgressReporter(session_factory, note.id, run.duration, clock)
    reporter.write({"duration_seconds": _duration(run.duration)})
    text = _collect(run, reporter, clock, start)
    if not text:
        raise TranscriptionError(
            TranscriptionErrorCode.NO_SPEECH, f"no speech recognised in {run.duration:.1f} s"
        )
    return TranscriptResult(text=text, duration=run.duration, transcribe_s=clock() - start)


def _store_done(
    session_factory: sessionmaker[Session], note_id: int, result: TranscriptResult, now: Now
) -> None:
    stored = _write(
        session_factory,
        note_id,
        {
            "transcription_status": TranscriptionStatus.DONE.value,
            "transcript": result.text,
            "progress": Decimal(1),
            "duration_seconds": _duration(result.duration),
            "transcribed_at": now(),
            "error_code": None,
            "transcription_error": None,
        },
    )
    if not stored:
        logger.warning("Audio note %s changed during transcription; result dropped", note_id)


def _store_failed(
    session_factory: sessionmaker[Session], note_id: int, error: TranscriptionError
) -> None:
    _write(
        session_factory,
        note_id,
        {
            "transcription_status": TranscriptionStatus.FAILED.value,
            "error_code": error.code.value,
            "transcription_error": error.detail[:MAX_ERROR_DETAIL],
            "progress": None,
            "transcript": None,
        },
    )


def current_initial_prompt() -> str | None:
    """Glossary hint from config/transcription.yaml; a broken file transcribes without it."""
    try:
        return get_transcription().initial_prompt()
    except ConfigError as exc:
        logger.error("Transcribing without the glossary hint: %s", exc)
        return None


def _log_done(note_id: int, result: TranscriptResult, wall_s: float) -> None:
    rtf = result.transcribe_s / result.duration if result.duration > 0 else 0.0
    logger.info(
        "Audio note %s transcribed: audio %.1f s, transcription %.1f s, wall %.1f s, RTF %.2f",
        note_id,
        result.duration,
        result.transcribe_s,
        wall_s,
        rtf,
    )


def _fail(session_factory: sessionmaker[Session], note_id: int, error: TranscriptionError) -> None:
    logger.error("Audio note %s failed (%s): %s", note_id, error.code.value, error.detail)
    _store_failed(session_factory, note_id, error)


def _finish(
    session_factory: sessionmaker[Session],
    note_id: int,
    outcome: TranscriptResult | TranscriptionError,
    now: Now,
    wall_s: float,
) -> None:
    """Store the result or the failure. A DB error is logged, never raised: the note then
    stays `processing` until the stale sweep (or a worker restart) picks it up."""
    try:
        if isinstance(outcome, TranscriptionError):
            _fail(session_factory, note_id, outcome)
        else:
            _store_done(session_factory, note_id, outcome, now)
            _log_done(note_id, outcome, wall_s)
    except SQLAlchemyError as exc:
        logger.error(
            "Audio note %s: result not saved (%s); it stays processing until the stale "
            "sweep or a worker restart",
            note_id,
            type(getattr(exc, "orig", None) or exc).__name__,
        )


def fail_stale_notes(session_factory: sessionmaker[Session], now: Now) -> int:
    """`processing` notes claimed more than STALE_AFTER_S ago -> `failed` (`timeout`).

    Covers a note whose final write was lost (DB outage) while this worker kept running.
    Safe because the worker is single-instance and the job never overlaps itself
    (max_instances=1), so the note being transcribed right now is never swept.
    """
    cutoff = now() - timedelta(seconds=STALE_AFTER_S)
    with session_factory() as session:
        ids = list(
            session.scalars(
                update(AudioNote)
                .where(
                    AudioNote.transcription_status == TranscriptionStatus.PROCESSING.value,
                    AudioNote.started_at < cutoff,
                )
                .values(
                    transcription_status=TranscriptionStatus.FAILED.value,
                    error_code=TranscriptionErrorCode.TIMEOUT.value,
                    transcription_error=f"stale: still processing after {STALE_AFTER_S:.0f} s",
                    progress=None,
                    transcript=None,
                )
                .returning(AudioNote.id)
            )
        )
        session.commit()
    for note_id in ids:
        logger.error(
            "Audio note %s failed (timeout): stale, processing for > %.0f s", note_id, STALE_AFTER_S
        )
    return len(ids)


def run_transcription_cycle(
    session_factory: sessionmaker[Session],
    transcriber: Transcriber,
    data_dir: Path,
    *,
    prompt_getter: Callable[[], str | None] = current_initial_prompt,
    now: Now = _utc_now,
    clock: Clock = time.monotonic,
) -> int | None:
    """Transcribe the oldest pending note, if any. Returns its id (None: queue empty).

    Never raises: every failure is logged and, when the DB allows it, stored on the note.
    """
    try:
        fail_stale_notes(session_factory, now)
        note = claim_next_note(session_factory, now)
    except SQLAlchemyError as exc:
        logger.error("Transcription: cannot read the queue (%s)", type(exc).__name__)
        return None
    if note is None:
        return None
    started = clock()
    outcome: TranscriptResult | TranscriptionError
    try:
        outcome = transcribe_note(
            session_factory, note, transcriber, data_dir, prompt_getter(), clock
        )
    except TranscriptionError as exc:
        outcome = exc
    except Exception as exc:
        logger.exception("Audio note %s: unexpected transcription error", note.id)
        detail = f"{type(exc).__name__}: {exc}"
        outcome = TranscriptionError(TranscriptionErrorCode.TRANSCRIPTION_FAILED, detail)
    _finish(session_factory, note.id, outcome, now, clock() - started)
    return note.id


def reset_interrupted_notes(session_factory: sessionmaker[Session]) -> int:
    """At worker start: `processing` notes belong to a stopped worker -> back to `pending`.

    Assumes ONE worker process (start.bat / `make dev` start exactly one): a second worker
    starting would re-queue the note the first one is transcribing.
    """
    try:
        with session_factory() as session:
            result = session.execute(
                update(AudioNote)
                .where(AudioNote.transcription_status == TranscriptionStatus.PROCESSING.value)
                .values(
                    transcription_status=TranscriptionStatus.PENDING.value,
                    progress=None,
                    started_at=None,
                )
            )
            session.commit()
    except Exception:
        logger.exception("Could not reset interrupted transcriptions")
        return 0
    count = int(getattr(result, "rowcount", 0))
    if count:
        logger.warning("Re-queued %s interrupted transcription(s) from a previous run", count)
    return count

"""Worker job `transcription` with a fake transcriber (no model, no audio decoding)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import make_session_factory
from app.models import Account, AudioNote, Trade
from app.models.enums import TranscriptionErrorCode
from app.services.transcriber import TranscribedSegment, TranscriptionError, TranscriptionRun
from app.worker import transcription_job as job
from app.worker.transcription_job import (
    claim_next_note,
    progress_value,
    reset_interrupted_notes,
    run_transcription_cycle,
)
from tests.test_trades_api import add_account, add_trade

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


@pytest.fixture
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def trade(session: Session) -> Trade:
    account: Account = add_account(session, "Alpha", 1)
    return add_trade(session, account)


class FakeClock:
    """Monotonic clock that advances by `step` seconds per call."""

    def __init__(self, step: float = 0.0) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


@dataclass
class FakeTranscriber:
    duration: float = 10.0
    segments: list[TranscribedSegment] = field(default_factory=list)
    load_error: Exception | None = None
    transcribe_error: Exception | None = None
    segment_error: Exception | None = None
    on_segment: Any = None  # called with the segment before it is yielded
    calls: list[tuple[Path, str | None]] = field(default_factory=list)
    settings: str = "model small int8, beam 1, vad on"

    def load(self) -> None:
        if self.load_error is not None:
            raise self.load_error

    def _iter(self) -> Iterator[TranscribedSegment]:
        for segment in self.segments:
            if self.on_segment is not None:
                self.on_segment(segment)
            yield segment
        if self.segment_error is not None:
            raise self.segment_error

    def transcribe(self, path: Path, initial_prompt: str | None) -> TranscriptionRun:
        self.calls.append((path, initial_prompt))
        if self.transcribe_error is not None:
            raise self.transcribe_error
        return TranscriptionRun(
            duration=self.duration, segments=self._iter(), settings=self.settings
        )


def add_note(session: Session, trade: Trade, data_dir: Path | None, **kw: Any) -> AudioNote:
    rel = kw.pop("file_path", f"audio/2026/11/{uuid.uuid4().hex}.webm")
    if data_dir is not None:
        target = data_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"audio")
    note = AudioNote(trade_id=trade.id, file_path=rel, mime_type="audio/webm", **kw)
    session.add(note)
    session.commit()
    return note


def run(
    factory: sessionmaker[Session],
    transcriber: FakeTranscriber,
    data_dir: Path,
    clock: FakeClock | None = None,
    prompt: str | None = "Торговий журнал. Терміни: FVG.",
) -> int | None:
    return run_transcription_cycle(
        factory,
        transcriber,
        data_dir,
        prompt_getter=lambda: prompt,
        now=lambda: NOW,
        clock=clock or FakeClock(),
    )


def reload(session: Session, note_id: int) -> AudioNote:
    session.expire_all()
    note = session.get(AudioNote, note_id)
    assert note is not None
    return note


def seg(end: float, text_: str) -> TranscribedSegment:
    return TranscribedSegment(end=end, text=text_)


# --- happy path ------------------------------------------------------------------------------


def test_done_with_transcript_and_duration(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    fake = FakeTranscriber(
        duration=118.4, segments=[seg(60, " Вхід по FVG, "), seg(118.4, " точка B. ")]
    )

    assert run(factory, fake, tmp_path) == note.id

    stored = reload(session, note.id)
    assert stored.transcription_status == "done"
    assert stored.transcript == "Вхід по FVG, точка B."
    assert stored.progress == Decimal("1.000")
    assert stored.duration_seconds == Decimal("118.400")
    assert stored.transcribed_at == NOW
    assert stored.started_at == NOW
    assert stored.error_code is None
    assert fake.calls == [((tmp_path / note.file_path).resolve(), "Торговий журнал. Терміни: FVG.")]


def test_empty_queue_returns_none(factory: sessionmaker[Session], tmp_path: Path) -> None:
    assert run(factory, FakeTranscriber(), tmp_path) is None


def test_logs_timing_line(
    factory: sessionmaker[Session],
    session: Session,
    trade: Trade,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    note = add_note(session, trade, tmp_path)
    fake = FakeTranscriber(duration=20.0, segments=[seg(20, "так")])
    with caplog.at_level(logging.INFO, logger="app.worker.transcription_job"):
        run(factory, fake, tmp_path, clock=FakeClock(step=1.0))
    line = next(r.getMessage() for r in caplog.records if "transcribed" in r.getMessage())
    assert f"Audio note {note.id} transcribed: audio 20.0 s" in line
    assert "RTF" in line
    assert line.endswith("(model small int8, beam 1, vad on)")  # decoding settings


def test_oldest_pending_first(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    newer = add_note(session, trade, tmp_path, created_at=NOW)
    older = add_note(session, trade, tmp_path, created_at=NOW - timedelta(minutes=5))
    add_note(
        session, trade, tmp_path, created_at=NOW - timedelta(hours=1), transcription_status="done"
    )
    fake = FakeTranscriber(segments=[seg(10, "a")])
    assert run(factory, fake, tmp_path) == older.id
    assert run(factory, fake, tmp_path) == newer.id
    assert run(factory, fake, tmp_path) is None


def test_claim_skips_locked_rows(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    first = add_note(session, trade, tmp_path, created_at=NOW - timedelta(minutes=2))
    second = add_note(session, trade, tmp_path, created_at=NOW - timedelta(minutes=1))
    with factory() as other:  # another worker holds the oldest row
        other.scalars(select(AudioNote).where(AudioNote.id == first.id).with_for_update()).one()
        claimed = claim_next_note(factory, lambda: NOW)
        assert claimed is not None
        assert claimed.id == second.id
        other.rollback()
    assert reload(session, first.id).transcription_status == "pending"
    assert reload(session, second.id).transcription_status == "processing"


def test_claim_sets_processing(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    claimed = claim_next_note(factory, lambda: NOW)
    assert claimed is not None
    stored = reload(session, note.id)
    assert stored.transcription_status == "processing"
    assert stored.started_at == NOW
    assert stored.progress == Decimal("0.000")


# --- progress ----------------------------------------------------------------------------------


def test_progress_written_while_processing(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    seen: list[tuple[str, Decimal | None, Decimal | None]] = []

    def observe(_: TranscribedSegment) -> None:
        current = reload(session, note.id)
        seen.append((current.transcription_status, current.progress, current.duration_seconds))

    segments = [seg(25, "a"), seg(50, "b"), seg(75, "c"), seg(100, "d")]
    fake = FakeTranscriber(duration=100.0, segments=segments, on_segment=observe)
    run(factory, fake, tmp_path, clock=FakeClock(step=1.0))

    assert [s[0] for s in seen] == ["processing"] * 4
    assert seen[0][2] == Decimal("100.000")  # duration written once decoded
    assert [s[1] for s in seen[1:]] == [Decimal("0.250"), Decimal("0.500"), Decimal("0.750")]
    assert reload(session, note.id).progress == Decimal("1.000")


def test_progress_with_vad_gaps_stays_below_one(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    """VAD skips silence: segment ends jump (and trailing silence has no segment), yet
    progress follows segment end / full duration, never reaches 1 while processing."""
    note = add_note(session, trade, tmp_path)
    seen: list[Decimal | None] = []

    def observe(_: TranscribedSegment) -> None:
        seen.append(reload(session, note.id).progress)

    segments = [seg(4, "a"), seg(9, "b"), seg(70, "c"), seg(119.995, "d"), seg(121, "e")]
    fake = FakeTranscriber(duration=120.0, segments=segments, on_segment=observe)
    run(factory, fake, tmp_path, clock=FakeClock(step=1.0))

    progress = [p for p in seen[1:] if p is not None]
    assert progress == [Decimal("0.033"), Decimal("0.075"), Decimal("0.583"), Decimal("0.999")]
    assert all(p <= Decimal("0.999") for p in progress)
    assert reload(session, note.id).progress == Decimal("1.000")


def test_progress_throttled_to_once_per_second(
    factory: sessionmaker[Session],
    session: Session,
    trade: Trade,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_note(session, trade, tmp_path)
    writes: list[dict[str, Any]] = []
    real_write = job._write

    def spy(f: sessionmaker[Session], note_id: int, values: dict[str, Any]) -> bool:
        writes.append(values)
        return real_write(f, note_id, values)

    monkeypatch.setattr(job, "_write", spy)
    segments = [seg(i, "x") for i in range(1, 21)]
    run(factory, FakeTranscriber(duration=20, segments=segments), tmp_path, FakeClock(step=0.1))
    progress_writes = [w for w in writes if set(w) == {"progress"}]
    # 20 segments, clock +0.1 s per call (2 calls per segment): about 4 writes, not 20.
    assert 2 <= len(progress_writes) <= 5


@pytest.mark.parametrize(
    ("end", "duration", "expected"),
    [
        (30.0, 120.0, Decimal("0.250")),
        (119.99, 120.0, Decimal("0.999")),
        (130.0, 120.0, Decimal("0.999")),
        (1.0, 3.0, Decimal("0.333")),
        (5.0, 0.0, None),
    ],
)
def test_progress_value(end: float, duration: float, expected: Decimal | None) -> None:
    assert progress_value(end, duration) == expected


# --- failures ----------------------------------------------------------------------------------


def _assert_failed(session: Session, note_id: int, code: str, detail: str) -> None:
    stored = reload(session, note_id)
    assert stored.transcription_status == "failed"
    assert stored.error_code == code
    assert stored.transcription_error is not None
    assert detail in stored.transcription_error
    assert stored.progress is None
    assert stored.transcript is None


def test_missing_file(
    factory: sessionmaker[Session],
    session: Session,
    trade: Trade,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    note = add_note(session, trade, None)
    fake = FakeTranscriber()
    run(factory, fake, tmp_path)
    _assert_failed(session, note.id, "audio_missing", "not found")
    assert fake.calls == []
    assert f"Audio note {note.id} failed (audio_missing)" in caplog.text


def test_stored_path_outside_audio_dir(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    note = add_note(session, trade, None, file_path="audio/../secret.txt")
    fake = FakeTranscriber()
    run(factory, fake, tmp_path)
    _assert_failed(session, note.id, "audio_missing", "outside")
    assert fake.calls == []


def test_no_speech(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    run(factory, FakeTranscriber(segments=[seg(3, "  "), seg(5, "")]), tmp_path)
    _assert_failed(session, note.id, "no_speech", "no speech")


def test_no_segments_is_no_speech(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    run(factory, FakeTranscriber(duration=4.0), tmp_path)
    _assert_failed(session, note.id, "no_speech", "4.0 s")
    assert reload(session, note.id).duration_seconds == Decimal("4.000")


@pytest.mark.parametrize(
    ("fake", "code"),
    [
        (
            FakeTranscriber(
                load_error=TranscriptionError(TranscriptionErrorCode.MODEL_UNAVAILABLE, "no net")
            ),
            "model_unavailable",
        ),
        (
            FakeTranscriber(
                transcribe_error=TranscriptionError(
                    TranscriptionErrorCode.AUDIO_UNREADABLE, "InvalidDataError: bad"
                )
            ),
            "audio_unreadable",
        ),
        (
            FakeTranscriber(
                segments=[seg(1, "a")],
                segment_error=TranscriptionError(
                    TranscriptionErrorCode.AUDIO_UNREADABLE, "late decode"
                ),
            ),
            "audio_unreadable",
        ),
        (
            FakeTranscriber(transcribe_error=RuntimeError("ctranslate2 boom")),
            "transcription_failed",
        ),
        (
            FakeTranscriber(segments=[seg(1, "a")], segment_error=MemoryError()),
            "transcription_failed",
        ),
    ],
)
def test_error_codes(
    factory: sessionmaker[Session],
    session: Session,
    trade: Trade,
    tmp_path: Path,
    fake: FakeTranscriber,
    code: str,
) -> None:
    note = add_note(session, trade, tmp_path)
    assert run(factory, fake, tmp_path) == note.id  # never raises
    stored = reload(session, note.id)
    assert stored.transcription_status == "failed"
    assert stored.error_code == code
    assert stored.transcription_error


def test_timeout_after_600_seconds_of_work(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    segments = [seg(i * 10, "x") for i in range(1, 100)]
    fake = FakeTranscriber(duration=1000, segments=segments)
    run(factory, fake, tmp_path, clock=FakeClock(step=100.0))
    _assert_failed(session, note.id, "timeout", "stopped after")


def test_failure_keeps_the_audio_file(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    run(factory, FakeTranscriber(transcribe_error=RuntimeError("x")), tmp_path)
    assert (tmp_path / note.file_path).is_file()


def test_next_note_runs_after_a_failure(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    bad = add_note(session, trade, None, created_at=NOW - timedelta(minutes=1))
    good = add_note(session, trade, tmp_path, created_at=NOW)
    fake = FakeTranscriber(segments=[seg(1, "ok")])
    run(factory, fake, tmp_path)
    run(factory, fake, tmp_path)
    assert reload(session, bad.id).transcription_status == "failed"
    assert reload(session, good.id).transcription_status == "done"


def test_retried_note_is_transcribed_again(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    note = add_note(session, trade, tmp_path)
    run(factory, FakeTranscriber(transcribe_error=RuntimeError("x")), tmp_path)
    stored = reload(session, note.id)
    stored.transcription_status = "pending"
    stored.error_code = None
    session.commit()
    run(factory, FakeTranscriber(segments=[seg(1, "друга спроба")]), tmp_path)
    stored = reload(session, note.id)
    assert stored.transcription_status == "done"
    assert stored.transcription_error is None


def test_broken_glossary_transcribes_without_prompt(
    session: Session, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config_files import ConfigError

    def broken() -> Any:
        raise ConfigError(Path("transcription.yaml"), ["glossary: bad"])

    monkeypatch.setattr(job, "get_transcription", broken)
    assert job.current_initial_prompt() is None
    assert "without the glossary hint" in caplog.text


def test_real_glossary_prompt() -> None:
    prompt = job.current_initial_prompt()
    assert prompt is not None
    assert "FVG" in prompt


# --- worker start ------------------------------------------------------------------------------


def test_reset_interrupted_notes(
    factory: sessionmaker[Session], session: Session, trade: Trade, tmp_path: Path
) -> None:
    stuck = add_note(
        session,
        trade,
        tmp_path,
        transcription_status="processing",
        progress=Decimal("0.5"),
        started_at=NOW,
    )
    done = add_note(session, trade, tmp_path, transcription_status="done", progress=Decimal(1))
    assert reset_interrupted_notes(factory) == 1
    stored = reload(session, stuck.id)
    assert stored.transcription_status == "pending"
    assert stored.progress is None
    assert stored.started_at is None
    assert reload(session, done.id).transcription_status == "done"


# --- lost final write / stale sweep ------------------------------------------------------------


def test_db_error_on_final_write_never_raises(
    factory: sessionmaker[Session],
    session: Session,
    trade: Trade,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sqlalchemy.exc import OperationalError

    note = add_note(session, trade, tmp_path)
    real_write = job._write

    def flaky(f: sessionmaker[Session], note_id: int, values: dict[str, Any]) -> bool:
        if "transcription_status" in values:  # the final done/failed write
            raise OperationalError("UPDATE audio_notes", {}, ConnectionRefusedError("down"))
        return real_write(f, note_id, values)

    monkeypatch.setattr(job, "_write", flaky)
    assert run(factory, FakeTranscriber(segments=[seg(1, "ok")]), tmp_path) == note.id
    assert run(factory, FakeTranscriber(transcribe_error=RuntimeError("x")), tmp_path) is None
    assert reload(session, note.id).transcription_status == "processing"
    assert f"Audio note {note.id}: result not saved (ConnectionRefusedError)" in caplog.text


def test_stale_processing_note_fails_with_timeout(
    factory: sessionmaker[Session],
    session: Session,
    trade: Trade,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stale_start = NOW - timedelta(seconds=job.STALE_AFTER_S + 1)
    stale = add_note(
        session,
        trade,
        tmp_path,
        transcription_status="processing",
        progress=Decimal("0.4"),
        started_at=stale_start,
    )
    recent = add_note(
        session,
        trade,
        tmp_path,
        transcription_status="processing",
        progress=Decimal("0.4"),
        started_at=NOW - timedelta(minutes=5),
    )

    assert run(factory, FakeTranscriber(), tmp_path) is None  # queue empty, sweep ran

    _assert_failed(session, stale.id, "timeout", "stale")
    assert reload(session, recent.id).transcription_status == "processing"
    assert f"Audio note {stale.id} failed (timeout)" in caplog.text

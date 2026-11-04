"""`python -m app.tools.transcribe_bench` with a fake transcriber (no model)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

from app.config import Settings
from app.models.enums import TranscriptionErrorCode
from app.services.transcriber import TranscribedSegment, TranscriptionError, TranscriptionRun
from app.tools import transcribe_bench


class FakeTranscriber:
    def __init__(self, *, fail_load: bool = False) -> None:
        self.fail_load = fail_load
        self.prompts: list[str | None] = []

    def load(self) -> None:
        if self.fail_load:
            raise TranscriptionError(TranscriptionErrorCode.MODEL_UNAVAILABLE, "offline")

    def _segments(self) -> Iterator[TranscribedSegment]:
        yield TranscribedSegment(end=10.0, text=" Вхід по FVG. ")

    def transcribe(self, path: Path, initial_prompt: str | None) -> TranscriptionRun:
        self.prompts.append(initial_prompt)
        if path.name == "bad.webm":
            raise TranscriptionError(TranscriptionErrorCode.AUDIO_UNREADABLE, "Invalid data")
        return TranscriptionRun(duration=30.0, segments=self._segments())


def test_prints_timing_and_transcript(settings: Settings) -> None:
    out = io.StringIO()
    fake = FakeTranscriber()
    code = transcribe_bench.main(
        ["a.webm", "--model", "base"],
        settings=settings,
        transcriber=fake,
        out=out,
        configure_logging=False,
    )
    text = out.getvalue()
    assert code == 0
    assert "Model base (int8" in text
    assert "Model load" in text
    assert "a.webm: audio 30.0 s, transcription" in text
    assert "RTF" in text
    assert "Вхід по FVG." in text
    assert fake.prompts[0] is not None
    assert "FVG" in fake.prompts[0]


def test_failed_file_gives_exit_code_1(settings: Settings) -> None:
    out = io.StringIO()
    code = transcribe_bench.main(
        ["a.webm", "bad.webm"],
        settings=settings,
        transcriber=FakeTranscriber(),
        out=out,
        configure_logging=False,
    )
    assert code == 1
    assert "bad.webm: FAILED (audio_unreadable)" in out.getvalue()


def test_model_load_failure(settings: Settings) -> None:
    out = io.StringIO()
    code = transcribe_bench.main(
        ["a.webm"],
        settings=settings,
        transcriber=FakeTranscriber(fail_load=True),
        out=out,
        configure_logging=False,
    )
    assert code == 1
    assert "Model load FAILED (model_unavailable)" in out.getvalue()

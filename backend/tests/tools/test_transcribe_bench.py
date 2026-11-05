"""`python -m app.tools.transcribe_bench` with a fake transcriber (no model)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import Settings
from app.models.enums import TranscriptionErrorCode
from app.services import transcriber as transcriber_mod
from app.services.transcriber import (
    TranscribedSegment,
    TranscriptionError,
    TranscriptionRun,
    WhisperOptions,
)
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


@pytest.fixture(autouse=True)
def _cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcriber_mod, "physical_cores", lambda: 12)


def _bench_settings(settings: Settings) -> Settings:
    """The code defaults for the decoding options, whatever the local .env says."""
    return settings.model_copy(
        update={
            "whisper_model": "small",
            "whisper_compute_type": "int8",
            "whisper_language": "uk",
            "whisper_beam_size": 1,
            "whisper_cpu_threads": "auto",
            "whisper_vad_filter": True,
            "whisper_condition_on_previous_text": False,
            "whisper_temperatures": (0.0, 0.4),
        }
    )


def _options(settings: Settings, argv: list[str]) -> WhisperOptions:
    args = transcribe_bench._parser().parse_args(["a.webm", *argv])
    return transcribe_bench._options(_bench_settings(settings), args)


def test_options_default_to_settings(settings: Settings) -> None:
    options = _options(settings, [])
    assert options == WhisperOptions.from_settings(_bench_settings(settings))
    assert options.cpu_threads == 12


def test_old_preset(settings: Settings) -> None:
    options = _options(settings, ["--preset", "old"])
    assert options.beam_size == 5
    assert options.vad_filter is False
    assert options.condition_on_previous_text is True
    assert options.temperatures == (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    assert options.cpu_threads == 0
    assert options.model == "small"


def test_flags_override_preset_and_settings(settings: Settings) -> None:
    options = _options(
        settings,
        [
            "--preset",
            "old",
            "--beam-size",
            "1",
            "--vad",
            "--no-condition-on-previous-text",
            "--temperatures",
            "0",
            "--cpu-threads",
            "auto",
            "--model",
            "base",
        ],
    )
    assert (options.beam_size, options.vad_filter, options.condition_on_previous_text) == (
        1,
        True,
        False,
    )
    assert options.temperatures == (0.0,)
    assert options.cpu_threads == 12
    assert options.model == "base"
    assert _options(settings, ["--no-vad", "--cpu-threads", "4"]).vad_filter is False


@pytest.mark.parametrize(
    "argv",
    [
        ["--temperatures", "0.4,0.2"],
        ["--temperatures", "2"],
        ["--cpu-threads", "-1"],
        ["--cpu-threads", "x"],
        ["--beam-size", "0"],
        ["--preset", "new"],
    ],
)
def test_invalid_flags_rejected(settings: Settings, argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        _options(settings, argv)


def test_prints_timing_and_settings_without_text_by_default(settings: Settings) -> None:
    out = io.StringIO()
    code = transcribe_bench.main(
        ["a.webm"],
        settings=_bench_settings(settings),
        transcriber=FakeTranscriber(),
        out=out,
        configure_logging=False,
    )
    text = out.getvalue()
    assert code == 0
    assert "Вхід по FVG." not in text
    line = next(line for line in text.splitlines() if line.startswith("a.webm:"))
    assert "audio 30.0 s, transcription" in line
    assert "wall" in line
    assert "RTF" in line
    assert "beam 1, vad on, condition_on_previous_text off, temperatures 0,0.4" in line
    assert "cpu threads 12" in line


def test_prints_timing_and_transcript(settings: Settings) -> None:
    out = io.StringIO()
    fake = FakeTranscriber()
    code = transcribe_bench.main(
        ["a.webm", "--model", "base", "--show-text"],
        settings=settings,
        transcriber=fake,
        out=out,
        configure_logging=False,
    )
    text = out.getvalue()
    assert code == 0
    assert "Settings: model base int8" in text
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

"""WhisperTranscriber with a stand-in `faster_whisper` module, error mapping, model cache.

The real model runs only when RUN_WHISPER_TESTS=1 (downloads the model once, slow).
"""

from __future__ import annotations

import math
import os
import struct
import sys
import types
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import av
import pytest

from app.config import Settings
from app.models.enums import TranscriptionErrorCode
from app.services import transcriber as mod
from app.services.transcriber import (
    TranscriptionError,
    WhisperOptions,
    WhisperTranscriber,
    classify_error,
)

OPTIONS = WhisperOptions(
    model="small", compute_type="int8", cpu_threads=0, language="uk", beam_size=5
)


class _Seg:
    def __init__(self, end: float, text: str) -> None:
        self.end = end
        self.text = text


class _Info:
    duration = 12.5


class FakeWhisperModel:
    instances: list[FakeWhisperModel] = []  # noqa: RUF012 - test registry
    init_error: Exception | None = None
    transcribe_error: Exception | None = None

    def __init__(self, model: str, **kwargs: Any) -> None:
        if FakeWhisperModel.init_error is not None:
            raise FakeWhisperModel.init_error
        self.model = model
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        FakeWhisperModel.instances.append(self)

    def transcribe(self, audio: str, **kwargs: Any) -> tuple[Iterator[_Seg], _Info]:
        self.calls.append({"audio": audio, **kwargs})
        if FakeWhisperModel.transcribe_error is not None:
            raise FakeWhisperModel.transcribe_error
        return iter([_Seg(5.0, " Вхід"), _Seg(12.5, " по FVG.")]), _Info()


@pytest.fixture
def fake_whisper(monkeypatch: pytest.MonkeyPatch) -> type[FakeWhisperModel]:
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(mod, "_models", {})
    FakeWhisperModel.instances = []
    FakeWhisperModel.init_error = None
    FakeWhisperModel.transcribe_error = None
    return FakeWhisperModel


def test_options_from_settings(settings: Settings) -> None:
    custom = settings.model_copy(
        update={"whisper_language": "  ", "whisper_model": " base ", "whisper_cpu_threads": 4}
    )
    options = WhisperOptions.from_settings(custom)
    assert options.language is None  # empty = auto-detect
    assert options.model == "base"
    assert options.cpu_threads == 4


def test_default_settings(settings: Settings) -> None:
    options = WhisperOptions.from_settings(settings)
    assert options == OPTIONS


def test_transcribe_passes_options(fake_whisper: type[FakeWhisperModel], tmp_path: Path) -> None:
    transcriber = WhisperTranscriber(OPTIONS)
    run = transcriber.transcribe(tmp_path / "a.webm", "Торговий журнал. Терміни: FVG.")
    assert run.duration == 12.5
    assert [(s.end, s.text) for s in run.segments] == [(5.0, " Вхід"), (12.5, " по FVG.")]
    (model,) = fake_whisper.instances
    assert model.model == "small"
    assert model.kwargs == {"device": "cpu", "compute_type": "int8", "cpu_threads": 0}
    assert model.calls == [
        {
            "audio": str(tmp_path / "a.webm"),
            "language": "uk",
            "beam_size": 5,
            "vad_filter": True,
            "initial_prompt": "Торговий журнал. Терміни: FVG.",
        }
    ]


def test_model_loaded_once_per_key(fake_whisper: type[FakeWhisperModel], tmp_path: Path) -> None:
    WhisperTranscriber(OPTIONS).load()
    WhisperTranscriber(OPTIONS).transcribe(tmp_path / "a.wav", None)
    assert len(fake_whisper.instances) == 1
    other = WhisperOptions(
        model="base", compute_type="int8", cpu_threads=0, language=None, beam_size=5
    )
    WhisperTranscriber(other).load()
    assert len(fake_whisper.instances) == 2


def test_model_load_failure_is_model_unavailable(fake_whisper: type[FakeWhisperModel]) -> None:
    fake_whisper.init_error = OSError("cannot download")
    with pytest.raises(TranscriptionError) as info:
        WhisperTranscriber(OPTIONS).load()
    assert info.value.code is TranscriptionErrorCode.MODEL_UNAVAILABLE
    assert "cannot download" in info.value.detail
    fake_whisper.init_error = None
    WhisperTranscriber(OPTIONS).load()  # a failure is not cached
    assert len(fake_whisper.instances) == 1


def test_decode_error_is_audio_unreadable(
    fake_whisper: type[FakeWhisperModel], tmp_path: Path
) -> None:
    fake_whisper.transcribe_error = av.error.InvalidDataError(1094995529, "Invalid data")
    with pytest.raises(TranscriptionError) as info:
        WhisperTranscriber(OPTIONS).transcribe(tmp_path / "a.webm", None)
    assert info.value.code is TranscriptionErrorCode.AUDIO_UNREADABLE


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (FileNotFoundError("gone"), TranscriptionErrorCode.AUDIO_MISSING),
        (
            av.error.InvalidDataError(1094995529, "Invalid data"),
            TranscriptionErrorCode.AUDIO_UNREADABLE,
        ),
        (RuntimeError("boom"), TranscriptionErrorCode.TRANSCRIPTION_FAILED),
        (ValueError("bad shape"), TranscriptionErrorCode.TRANSCRIPTION_FAILED),
        (
            TranscriptionError(TranscriptionErrorCode.TIMEOUT, "x"),
            TranscriptionErrorCode.TIMEOUT,
        ),
    ],
)
def test_classify_error(exc: Exception, code: TranscriptionErrorCode) -> None:
    assert classify_error(exc).code is code


def test_segment_errors_are_classified() -> None:
    def broken() -> Iterator[_Seg]:
        yield _Seg(1.0, "a")
        raise av.error.InvalidDataError(1094995529, "Invalid data")

    segments = mod._segments(broken())
    assert next(segments).text == "a"
    with pytest.raises(TranscriptionError) as info:
        next(segments)
    assert info.value.code is TranscriptionErrorCode.AUDIO_UNREADABLE


def _tone_wav(path: Path, seconds: float = 2.0, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(seconds * rate))
        )
        out.writeframes(frames)
    return path


@pytest.mark.skipif(
    os.environ.get("RUN_WHISPER_TESTS") != "1",
    reason="real faster-whisper model; set RUN_WHISPER_TESTS=1 (downloads the model)",
)
@pytest.mark.filterwarnings("ignore")  # huggingface_hub cache warnings on Windows
def test_real_model_on_generated_wav(tmp_path: Path, settings: Settings) -> None:
    transcriber = WhisperTranscriber(WhisperOptions.from_settings(settings))
    transcriber.load()
    run = transcriber.transcribe(_tone_wav(tmp_path / "tone.wav"), None)
    assert run.duration == pytest.approx(2.0, abs=0.05)
    list(run.segments)  # a pure tone has no speech; it must decode and finish


def test_real_decoder_rejects_garbage(tmp_path: Path) -> None:
    """PyAV (the decoder faster-whisper uses) raises an FFmpegError for non-audio bytes."""
    path = tmp_path / "bad.webm"
    path.write_bytes(b"not audio at all" * 10)
    with pytest.raises(av.error.FFmpegError) as info:
        av.open(str(path))
    assert classify_error(info.value).code is TranscriptionErrorCode.AUDIO_UNREADABLE


def test_faster_whisper_decodes_with_the_locked_pyav(tmp_path: Path) -> None:
    """Default run, no model: catches a PyAV bump that breaks faster-whisper's decoder
    (PyAV 19 removed `metadata_errors`, see DECISIONS.md)."""
    from faster_whisper.audio import decode_audio

    audio = decode_audio(str(_tone_wav(tmp_path / "tone.wav", seconds=1.0)))
    assert len(audio) == pytest.approx(16000, abs=160)

"""Speech-to-text behind a small Protocol; the real one is local faster-whisper (worker only).

`faster_whisper` (and PyAV) are imported lazily inside `WhisperTranscriber`, so the API
process and the tests never load them. The model is loaded once per process and cached by
(model, compute type, CPU threads).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings
from app.models.enums import TranscriptionErrorCode

logger = logging.getLogger(__name__)

WHISPER_DEVICE = "cpu"  # no CUDA on Borys's laptop; "auto" may pick a broken GPU setup


class TranscriptionError(Exception):
    """A failure with a stable code for the UI; `detail` is English, for logs only."""

    def __init__(self, code: TranscriptionErrorCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TranscribedSegment:
    end: float  # seconds from the start of the audio
    text: str


@dataclass(frozen=True)
class TranscriptionRun:
    """Audio duration (known once decoded) and lazily produced segments."""

    duration: float
    segments: Iterator[TranscribedSegment]


class Transcriber(Protocol):
    def load(self) -> None:
        """Load the model (may download it). Raises TranscriptionError(model_unavailable)."""
        ...

    def transcribe(self, path: Path, initial_prompt: str | None) -> TranscriptionRun:
        """Decode and start transcribing. Raises TranscriptionError for known failures."""
        ...


@dataclass(frozen=True)
class WhisperOptions:
    model: str
    compute_type: str
    cpu_threads: int
    language: str | None
    beam_size: int

    @classmethod
    def from_settings(cls, settings: Settings) -> WhisperOptions:
        return cls(
            model=settings.whisper_model.strip(),
            compute_type=settings.whisper_compute_type.strip(),
            cpu_threads=settings.whisper_cpu_threads,
            language=settings.whisper_language_code,
            beam_size=settings.whisper_beam_size,
        )


_models: dict[tuple[str, str, int], Any] = {}
_models_lock = threading.Lock()


def _load_model(options: WhisperOptions) -> Any:
    key = (options.model, options.compute_type, options.cpu_threads)
    with _models_lock:
        if key in _models:
            return _models[key]
        try:
            from faster_whisper import WhisperModel  # lazy: heavy, worker-only

            model = WhisperModel(
                options.model,
                device=WHISPER_DEVICE,
                compute_type=options.compute_type,
                cpu_threads=options.cpu_threads,
            )
        except Exception as exc:
            raise TranscriptionError(
                TranscriptionErrorCode.MODEL_UNAVAILABLE,
                f"cannot load Whisper model {options.model!r} "
                f"({options.compute_type}): {type(exc).__name__}: {exc}",
            ) from exc
        _models[key] = model
        logger.info("Whisper model %r loaded (%s, cpu)", options.model, options.compute_type)
        return model


def classify_error(exc: Exception) -> TranscriptionError:
    """Map a decode/transcribe exception to an error code (PyAV errors = unreadable audio)."""
    if isinstance(exc, TranscriptionError):
        return exc
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, FileNotFoundError):  # av.error.FileNotFoundError subclasses it
        return TranscriptionError(TranscriptionErrorCode.AUDIO_MISSING, detail)
    try:
        import av  # lazy: shipped with faster-whisper

        decode_errors: tuple[type[BaseException], ...] = (av.error.FFmpegError,)
    except ImportError:
        decode_errors = ()
    if decode_errors and isinstance(exc, decode_errors):
        return TranscriptionError(TranscriptionErrorCode.AUDIO_UNREADABLE, detail)
    return TranscriptionError(TranscriptionErrorCode.TRANSCRIPTION_FAILED, detail)


def _segments(raw: Iterable[Any]) -> Iterator[TranscribedSegment]:
    try:
        for segment in raw:
            yield TranscribedSegment(end=float(segment.end), text=str(segment.text))
    except Exception as exc:
        raise classify_error(exc) from exc


class WhisperTranscriber:
    """faster-whisper on the CPU with VAD (silence skipped) and the glossary prompt."""

    def __init__(self, options: WhisperOptions) -> None:
        self.options = options

    def load(self) -> None:
        _load_model(self.options)

    def transcribe(self, path: Path, initial_prompt: str | None) -> TranscriptionRun:
        model = _load_model(self.options)
        try:
            raw, info = model.transcribe(
                str(path),
                language=self.options.language,
                beam_size=self.options.beam_size,
                vad_filter=True,
                initial_prompt=initial_prompt,
            )
        except Exception as exc:
            raise classify_error(exc) from exc
        return TranscriptionRun(duration=float(info.duration), segments=_segments(raw))

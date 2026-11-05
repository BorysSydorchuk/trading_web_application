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

from app.config import CpuThreadsSetting, Settings
from app.models.enums import TranscriptionErrorCode
from app.services.cpu_cores import physical_cores

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
    settings: str = ""  # decoding settings used, for the timing log line


class Transcriber(Protocol):
    def load(self) -> None:
        """Load the model (may download it). Raises TranscriptionError(model_unavailable)."""
        ...

    def transcribe(self, path: Path, initial_prompt: str | None) -> TranscriptionRun:
        """Decode and start transcribing. Raises TranscriptionError for known failures."""
        ...


def resolve_cpu_threads(setting: CpuThreadsSetting) -> int:
    """`auto` -> physical core count (detected once); an int is used as is (0 = library)."""
    return physical_cores() if setting == "auto" else setting


@dataclass(frozen=True)
class WhisperOptions:
    model: str
    compute_type: str
    cpu_threads: int  # resolved; 0 = library default
    language: str | None
    beam_size: int
    vad_filter: bool = True
    condition_on_previous_text: bool = False
    temperatures: tuple[float, ...] = (0.0, 0.4)

    @classmethod
    def from_settings(cls, settings: Settings) -> WhisperOptions:
        return cls(
            model=settings.whisper_model.strip(),
            compute_type=settings.whisper_compute_type.strip(),
            cpu_threads=resolve_cpu_threads(settings.whisper_cpu_threads),
            language=settings.whisper_language_code,
            beam_size=settings.whisper_beam_size,
            vad_filter=settings.whisper_vad_filter,
            condition_on_previous_text=settings.whisper_condition_on_previous_text,
            temperatures=settings.whisper_temperatures,
        )

    def describe(self) -> str:
        """One-line summary for logs and the bench, e.g. `small int8, beam 1, vad on, ...`."""
        threads = str(self.cpu_threads) if self.cpu_threads else "library default"
        temps = ",".join(f"{t:g}" for t in self.temperatures)
        return (
            f"model {self.model} {self.compute_type}, language {self.language or 'auto'}, "
            f"beam {self.beam_size}, vad {'on' if self.vad_filter else 'off'}, "
            f"condition_on_previous_text {'on' if self.condition_on_previous_text else 'off'}, "
            f"temperatures {temps}, cpu threads {threads}"
        )

    def transcribe_kwargs(self, initial_prompt: str | None) -> dict[str, Any]:
        """Keyword arguments for faster-whisper's `WhisperModel.transcribe`."""
        return {
            "language": self.language,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "condition_on_previous_text": self.condition_on_previous_text,
            "temperature": list(self.temperatures),
            "initial_prompt": initial_prompt,
        }


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
        logger.info("Whisper model loaded (cpu): %s", options.describe())
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
    """faster-whisper on the CPU with the configured decoding options and glossary prompt."""

    def __init__(self, options: WhisperOptions) -> None:
        self.options = options

    def load(self) -> None:
        _load_model(self.options)

    def transcribe(self, path: Path, initial_prompt: str | None) -> TranscriptionRun:
        model = _load_model(self.options)
        try:
            raw, info = model.transcribe(
                str(path), **self.options.transcribe_kwargs(initial_prompt)
            )
        except Exception as exc:
            raise classify_error(exc) from exc
        # info.duration is the full audio (before VAD); segment ends are on that timeline.
        return TranscriptionRun(
            duration=float(info.duration),
            segments=_segments(raw),
            settings=self.options.describe(),
        )

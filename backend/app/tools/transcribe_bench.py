"""Time local faster-whisper on audio files with the app's settings (QA timing for M3).

    (repo root)  make whisper-bench FILES="a.webm b.webm"
                 make whisper-bench FILES=note.webm BENCH_ARGS="--preset old --show-text"
                 make whisper-bench FILES=note.webm WHISPER_BEAM_SIZE=5 WHISPER_VAD_FILTER=false

Uses the same transcriber, options and glossary hint (config/transcription.yaml) as the
worker; no DB. Precedence, lowest first: WHISPER_* from .env, then the environment (incl.
WHISPER_*=... on the make command line), then `--preset old`, then explicit flags.
`--preset old` is the pre-M3-11 decoding (beam 5, VAD on, condition_on_previous_text on,
faster-whisper's default temperatures 0,0.2,...,1.0, library-default threads); the model,
compute type and language are not part of the preset. Prints per file: audio duration,
transcription time (decode + transcribe), wall time (incl. the model load on the first
file, like the worker's first note), RTF (= transcription / audio) and the settings; the
transcript with `--show-text`.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, TextIO

from app.config import MAX_WHISPER_CPU_THREADS, Settings, get_settings, parse_temperatures
from app.logging_setup import setup_logging
from app.services.transcriber import (
    Transcriber,
    TranscriptionError,
    WhisperOptions,
    WhisperTranscriber,
    resolve_cpu_threads,
)
from app.worker.transcription_job import current_initial_prompt

LOG_FILE = "whisper_bench.log"
FASTER_WHISPER_DEFAULT_TEMPERATURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
# What the worker ran before M3-11: config default beam 5 and threads 0, `vad_filter=True`
# hard-coded, condition_on_previous_text and temperature not passed (library defaults).
OLD_PRESET: dict[str, Any] = {
    "beam_size": 5,
    "vad_filter": True,
    "condition_on_previous_text": True,
    "temperatures": FASTER_WHISPER_DEFAULT_TEMPERATURES,
    "cpu_threads": 0,
}


def _temperatures(text: str) -> tuple[float, ...]:
    try:
        return parse_temperatures(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _cpu_threads(text: str) -> int:
    value = text.strip().lower()
    if value == "auto":
        return resolve_cpu_threads("auto")
    if not value.isdigit() or int(value) > MAX_WHISPER_CPU_THREADS:
        raise argparse.ArgumentTypeError(
            f"`auto`, 0 (library default) or a count up to {MAX_WHISPER_CPU_THREADS}"
        )
    return int(value)


def _beam_size(text: str) -> int:
    if not text.strip().isdigit() or not 1 <= int(text) <= 20:
        raise argparse.ArgumentTypeError("an integer 1..20")
    return int(text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("files", nargs="+", type=Path, help="audio files to transcribe")
    parser.add_argument("--preset", choices=["old"], help="old = pre-M3-11 decoding settings")
    parser.add_argument("--model", help="override WHISPER_MODEL (e.g. base, small)")
    parser.add_argument("--compute-type", help="override WHISPER_COMPUTE_TYPE (e.g. int8)")
    parser.add_argument("--beam-size", type=_beam_size, help="override WHISPER_BEAM_SIZE")
    parser.add_argument(
        "--vad", action=argparse.BooleanOptionalAction, help="override WHISPER_VAD_FILTER"
    )
    parser.add_argument(
        "--condition-on-previous-text",
        action=argparse.BooleanOptionalAction,
        help="override WHISPER_CONDITION_ON_PREVIOUS_TEXT",
    )
    parser.add_argument(
        "--temperatures", type=_temperatures, help="override WHISPER_TEMPERATURES, e.g. 0,0.4"
    )
    parser.add_argument(
        "--cpu-threads", type=_cpu_threads, help="override WHISPER_CPU_THREADS (auto, 0, N)"
    )
    parser.add_argument("--show-text", action="store_true", help="print each transcript")
    return parser


def _options(settings: Settings, args: argparse.Namespace) -> WhisperOptions:
    options = WhisperOptions.from_settings(settings)
    if args.preset == "old":
        options = replace(options, **OLD_PRESET)
    overrides: dict[str, Any] = {
        "model": args.model.strip() if args.model else None,
        "compute_type": args.compute_type.strip() if args.compute_type else None,
        "beam_size": args.beam_size,
        "vad_filter": args.vad,
        "condition_on_previous_text": args.condition_on_previous_text,
        "temperatures": args.temperatures,
        "cpu_threads": args.cpu_threads,
    }
    return replace(options, **{k: v for k, v in overrides.items() if v is not None})


def bench_file(
    transcriber: Transcriber,
    path: Path,
    prompt: str | None,
    out: TextIO,
    *,
    settings_text: str,
    show_text: bool,
) -> bool:
    """Load (cached after the first file) and transcribe one file; print its timing."""
    wall_start = time.perf_counter()
    transcriber.load()  # TranscriptionError(model_unavailable) is handled by the caller
    start = time.perf_counter()
    try:
        run = transcriber.transcribe(path, prompt)
        text = " ".join(s.text.strip() for s in run.segments if s.text.strip())
    except TranscriptionError as exc:
        print(f"{path}: FAILED ({exc.code.value}) {exc.detail}", file=out)
        return False
    end = time.perf_counter()
    elapsed = end - start
    rtf = elapsed / run.duration if run.duration > 0 else 0.0
    print(
        f"{path}: audio {run.duration:.1f} s, transcription {elapsed:.1f} s, "
        f"wall {end - wall_start:.1f} s, RTF {rtf:.2f} [{settings_text}]",
        file=out,
    )
    if show_text:
        print(f"  {text or '(no speech)'}", file=out)
    return True


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    transcriber: Transcriber | None = None,
    out: TextIO | None = None,
    configure_logging: bool = True,
) -> int:
    settings = settings or get_settings()
    args = _parser().parse_args(argv)
    out = out or sys.stdout
    if isinstance(out, io.TextIOWrapper):
        out.reconfigure(encoding="utf-8")  # Ukrainian text on a cp1252 console
    if configure_logging:
        setup_logging(LOG_FILE, settings)
    options = _options(settings, args)
    transcriber = transcriber or WhisperTranscriber(options)
    settings_text = options.describe()
    print(f"Settings: {settings_text}", file=out)
    prompt = current_initial_prompt()
    results: list[bool] = []
    for path in args.files:
        try:
            results.append(
                bench_file(
                    transcriber,
                    path,
                    prompt,
                    out,
                    settings_text=settings_text,
                    show_text=args.show_text,
                )
            )
        except TranscriptionError as exc:
            print(f"Model load FAILED ({exc.code.value}): {exc.detail}", file=out)
            return 1
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

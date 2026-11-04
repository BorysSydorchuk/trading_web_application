"""Time local faster-whisper on audio files with the app's settings (QA timing for M3).

    (repo root)  make whisper-bench FILES="a.webm b.webm"
                 make whisper-bench FILES=note.webm WHISPER_MODEL=base

Uses the same transcriber, options (WHISPER_* from .env) and glossary hint
(config/transcription.yaml) as the worker; no DB. Prints, per file: audio duration,
transcription wall time and real-time factor (RTF = transcription time / audio duration),
then the transcript. The model load time (download on first use) is printed once.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from app.config import Settings, get_settings
from app.logging_setup import setup_logging
from app.services.transcriber import (
    Transcriber,
    TranscriptionError,
    WhisperOptions,
    WhisperTranscriber,
)
from app.worker.transcription_job import current_initial_prompt

LOG_FILE = "whisper_bench.log"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("files", nargs="+", type=Path, help="audio files to transcribe")
    parser.add_argument("--model", help="override WHISPER_MODEL (e.g. base, small)")
    parser.add_argument("--compute-type", help="override WHISPER_COMPUTE_TYPE (e.g. int8)")
    return parser


def _options(settings: Settings, args: argparse.Namespace) -> WhisperOptions:
    options = WhisperOptions.from_settings(settings)
    if args.model:
        options = replace(options, model=args.model.strip())
    if args.compute_type:
        options = replace(options, compute_type=args.compute_type.strip())
    return options


def bench_file(transcriber: Transcriber, path: Path, prompt: str | None, out: TextIO) -> bool:
    """Transcribe one file and print its timing. False when it failed."""
    start = time.perf_counter()
    try:
        run = transcriber.transcribe(path, prompt)
        text = " ".join(s.text.strip() for s in run.segments if s.text.strip())
    except TranscriptionError as exc:
        print(f"{path}: FAILED ({exc.code.value}) {exc.detail}", file=out)
        return False
    elapsed = time.perf_counter() - start
    rtf = elapsed / run.duration if run.duration > 0 else 0.0
    print(
        f"{path}: audio {run.duration:.1f} s, transcription {elapsed:.1f} s, RTF {rtf:.2f}",
        file=out,
    )
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
    threads = options.cpu_threads or "auto"
    print(
        f"Model {options.model} ({options.compute_type}, cpu threads {threads}), "
        f"language {options.language or 'auto'}, beam {options.beam_size}",
        file=out,
    )
    start = time.perf_counter()
    try:
        transcriber.load()
    except TranscriptionError as exc:
        print(f"Model load FAILED ({exc.code.value}): {exc.detail}", file=out)
        return 1
    print(f"Model load {time.perf_counter() - start:.1f} s", file=out)
    prompt = current_initial_prompt()
    results = [bench_file(transcriber, path, prompt, out) for path in args.files]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

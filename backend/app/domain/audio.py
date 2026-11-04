"""Voice-note storage rules (docs/api.md M3): allowed types, size limit, file layout.

Pure functions: no I/O except `resolve_audio_path`, which only resolves paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

AUDIO_SUBDIR = "audio"
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MiB

# Base content type (parameters stripped, lower-cased) -> file extension.
AUDIO_EXTENSIONS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}


def base_content_type(header: str | None) -> str | None:
    """`audio/webm;codecs=opus` -> `audio/webm`; None for a missing/blank header."""
    if header is None:
        return None
    base = header.split(";", 1)[0].strip().lower()
    return base or None


def audio_extension(content_type: str | None) -> str | None:
    """File extension for an allowed audio content type, else None."""
    base = base_content_type(content_type)
    return AUDIO_EXTENSIONS.get(base) if base is not None else None


def new_audio_relpath(extension: str, now: datetime, file_id: uuid.UUID | None = None) -> str:
    """`audio/YYYY/MM/<uuid>.<ext>` (POSIX separators, relative to DATA_DIR); `now` is UTC."""
    name = f"{(file_id or uuid.uuid4()).hex}.{extension}"
    return str(PurePosixPath(AUDIO_SUBDIR, f"{now.year:04d}", f"{now.month:02d}", name))


def resolve_audio_path(data_dir: Path, relpath: str) -> Path | None:
    """Absolute path of a stored note, or None when it would leave `<data_dir>/audio`.

    Guards against path traversal (`..`, absolute paths, drive letters) in stored values.
    """
    root = (data_dir / AUDIO_SUBDIR).resolve()
    candidate = (data_dir / relpath).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        return None
    return candidate

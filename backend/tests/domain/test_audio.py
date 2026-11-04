"""Voice-note storage rules: content types, file layout, path traversal guard."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.audio import (
    audio_extension,
    base_content_type,
    new_audio_relpath,
    resolve_audio_path,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("audio/webm", "webm"),
        ("audio/webm;codecs=opus", "webm"),
        ("Audio/WebM ; codecs=opus", "webm"),
        ("audio/ogg; codecs=opus", "ogg"),
        ("audio/mp4", "m4a"),
        ("audio/mpeg", "mp3"),
        ("audio/wav", "wav"),
        ("audio/x-wav", None),
        ("video/webm", None),
        ("application/octet-stream", None),
        ("", None),
        (None, None),
    ],
)
def test_audio_extension(header: str | None, expected: str | None) -> None:
    assert audio_extension(header) == expected


def test_base_content_type_strips_parameters() -> None:
    assert base_content_type("audio/webm;codecs=opus") == "audio/webm"
    assert base_content_type("  ") is None


def test_new_audio_relpath_layout() -> None:
    file_id = uuid.UUID("12345678123456781234567812345678")
    path = new_audio_relpath("webm", datetime(2026, 3, 5, 23, 59, tzinfo=UTC), file_id)
    assert path == "audio/2026/03/12345678123456781234567812345678.webm"


def test_new_audio_relpath_is_unique() -> None:
    now = datetime(2026, 11, 4, tzinfo=UTC)
    assert new_audio_relpath("ogg", now) != new_audio_relpath("ogg", now)


def test_resolve_inside_audio_dir(tmp_path: Path) -> None:
    resolved = resolve_audio_path(tmp_path, "audio/2026/11/a.webm")
    assert resolved == (tmp_path / "audio" / "2026" / "11" / "a.webm").resolve()


@pytest.mark.parametrize(
    "relpath",
    [
        "../secret.txt",
        "audio/../../secret.txt",
        "audio/../config.yaml",
        "audio",
        "other/a.webm",
        "C:/Windows/win.ini",
        "/etc/passwd",
    ],
)
def test_resolve_rejects_paths_outside_audio_dir(tmp_path: Path, relpath: str) -> None:
    assert resolve_audio_path(tmp_path, relpath) is None

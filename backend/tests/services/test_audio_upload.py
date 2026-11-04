"""`save_upload`: streamed write with the size limit enforced while reading."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.errors import ApiError
from app.services.audio_notes import save_upload


async def _chunks(parts: list[bytes], consumed: list[int]) -> AsyncIterator[bytes]:
    for part in parts:
        consumed.append(len(part))
        yield part


def test_writes_all_chunks(tmp_path: Path) -> None:
    target = tmp_path / "audio" / "2026" / "11" / "a.webm"
    consumed: list[int] = []
    size = asyncio.run(save_upload(_chunks([b"ab", b"", b"cd"], consumed), target, 10))
    assert size == 4
    assert target.read_bytes() == b"abcd"
    assert not target.with_name("a.webm.part").exists()


def test_stops_reading_once_over_the_limit(tmp_path: Path) -> None:
    target = tmp_path / "a.webm"
    consumed: list[int] = []
    parts = [b"x" * 4] * 10
    with pytest.raises(ApiError) as info:
        asyncio.run(save_upload(_chunks(parts, consumed), target, 10))
    assert info.value.status_code == 413
    assert info.value.code == "audio_too_large"
    assert len(consumed) == 3  # 12 bytes > 10: the rest of the body is never read
    assert list(tmp_path.iterdir()) == []


def test_empty_body_leaves_no_file(tmp_path: Path) -> None:
    target = tmp_path / "a.webm"
    with pytest.raises(ApiError) as info:
        asyncio.run(save_upload(_chunks([b""], []), target, 10))
    assert info.value.status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_client_disconnect_removes_partial_file(tmp_path: Path) -> None:
    async def broken() -> AsyncIterator[bytes]:
        yield b"abc"
        raise ConnectionResetError("client went away")

    with pytest.raises(ConnectionResetError):
        asyncio.run(save_upload(broken(), tmp_path / "a.webm", 10))
    assert list(tmp_path.iterdir()) == []


def test_large_upload_is_written_in_batches(tmp_path: Path) -> None:
    target = tmp_path / "a.wav"
    parts = [b"y" * 300_000] * 8  # 2.4 MB, more than one write batch
    size = asyncio.run(save_upload(_chunks(parts, []), target, 25 * 1024 * 1024))
    assert size == 2_400_000
    assert target.stat().st_size == 2_400_000

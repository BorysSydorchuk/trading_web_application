"""Physical core detection (Windows record parsing, fallbacks)."""

from __future__ import annotations

import logging
import os
import struct
import sys

import pytest

from app.services import cpu_cores
from app.services.cpu_cores import count_core_records, detect_physical_cores


def _record(relationship: int, size: int = 48) -> bytes:
    return struct.pack("<II", relationship, size) + b"\0" * (size - 8)


def _info(cores: int) -> bytes:
    return b"".join(_record(cpu_cores.RELATION_PROCESSOR_CORE) for _ in range(cores))


def test_counts_core_records_only() -> None:
    buffer = _info(3) + _record(2, 80) + _info(1)  # 2 = RelationCache, not a core
    assert count_core_records(buffer) == 4
    assert count_core_records(b"") == 0


@pytest.mark.parametrize(
    "buffer",
    [
        struct.pack("<II", 0, 100) + b"\0" * 8,  # record longer than the buffer
        struct.pack("<II", 0, 4),  # size smaller than the header
        _info(1) + b"\0\0\0",  # truncated header
    ],
)
def test_malformed_buffer_raises(buffer: bytes) -> None:
    with pytest.raises(ValueError, match="record"):
        count_core_records(buffer)


def test_windows_detection(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.services.cpu_cores"):
        cores = detect_physical_cores(
            platform="win32", windows_info=lambda: _info(12), cpu_count=lambda: 16
        )
    assert cores == 12
    assert "12 physical cores detected" in caplog.text


def _fail() -> bytes:
    raise OSError("GetLogicalProcessorInformationEx failed (error 5)")


def test_windows_failure_falls_back_to_half_logical(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.services.cpu_cores"):
        cores = detect_physical_cores(platform="win32", windows_info=_fail, cpu_count=lambda: 16)
    assert cores == 8
    assert "error 5" in caplog.text


def test_unexpected_error_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> bytes:
        raise TypeError("wrong argtypes")

    with caplog.at_level(logging.WARNING, logger="app.services.cpu_cores"):
        cores = detect_physical_cores(platform="win32", windows_info=broken, cpu_count=lambda: 16)
    assert cores == 8
    assert "TypeError" in caplog.text


def test_zero_core_records_fall_back() -> None:
    assert (
        detect_physical_cores(platform="win32", windows_info=lambda: b"", cpu_count=lambda: 4) == 2
    )


def test_non_windows_falls_back() -> None:
    assert detect_physical_cores(platform="linux", cpu_count=lambda: 1) == 1


def test_unknown_cpu_count_is_library_default(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.services.cpu_cores"):
        cores = detect_physical_cores(platform="win32", windows_info=_fail, cpu_count=lambda: None)
    assert cores == cpu_cores.LIBRARY_DEFAULT_THREADS
    assert "library default" in caplog.text


def test_physical_cores_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake() -> int:
        calls.append(1)
        return 6

    cpu_cores.physical_cores.cache_clear()
    monkeypatch.setattr(cpu_cores, "detect_physical_cores", fake)
    try:
        assert cpu_cores.physical_cores() == 6
        assert cpu_cores.physical_cores() == 6
        assert len(calls) == 1
    finally:
        cpu_cores.physical_cores.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="real kernel32 call")
def test_real_windows_call_counts_at_least_one_core() -> None:
    cores = count_core_records(cpu_cores._windows_core_info())
    logical = os.cpu_count() or cores
    assert 1 <= cores <= logical

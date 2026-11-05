"""Physical CPU core count for Whisper's `cpu_threads` (stdlib only, no psutil).

Windows: `GetLogicalProcessorInformationEx(RelationProcessorCore)` via ctypes, one record
per physical core (a hyper-threaded core counts once). Elsewhere, or when the call fails:
`os.cpu_count() // 2` (assumes 2 threads per core), or 0 (= library default) when even
that is unknown. The result is detected and logged once per process.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
from collections.abc import Callable
from functools import lru_cache

logger = logging.getLogger(__name__)

RELATION_PROCESSOR_CORE = 0  # LOGICAL_PROCESSOR_RELATIONSHIP.RelationProcessorCore
ERROR_INSUFFICIENT_BUFFER = 122
LIBRARY_DEFAULT_THREADS = 0  # CTranslate2 picks the thread count
_RECORD_HEADER = struct.Struct("<II")  # Relationship (DWORD), Size (DWORD)
_MAX_BUFFER = 1 << 20  # sanity cap for the info buffer (a few KB on a laptop)


def count_core_records(buffer: bytes) -> int:
    """Number of RelationProcessorCore records in a GetLogicalProcessorInformationEx buffer.

    Raises ValueError for a malformed buffer (a record size that does not fit).
    """
    count = 0
    offset = 0
    while offset < len(buffer):
        if offset + _RECORD_HEADER.size > len(buffer):
            raise ValueError(f"truncated record header at offset {offset}")
        relationship, size = _RECORD_HEADER.unpack_from(buffer, offset)
        if size < _RECORD_HEADER.size or offset + size > len(buffer):
            raise ValueError(f"bad record size {size} at offset {offset}")
        if relationship == RELATION_PROCESSOR_CORE:
            count += 1
        offset += size
    return count


def _windows_core_info() -> bytes:
    """Raw RelationProcessorCore records from kernel32. Raises OSError on failure."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel32.GetLogicalProcessorInformationEx
    query.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    length = wintypes.DWORD(0)
    if query(RELATION_PROCESSOR_CORE, None, ctypes.byref(length)):
        return b""
    error = ctypes.get_last_error()
    if error != ERROR_INSUFFICIENT_BUFFER or not 0 < length.value <= _MAX_BUFFER:
        raise OSError(f"GetLogicalProcessorInformationEx size query failed (error {error})")
    buffer = ctypes.create_string_buffer(length.value)
    if not query(RELATION_PROCESSOR_CORE, buffer, ctypes.byref(length)):
        error = ctypes.get_last_error()
        raise OSError(f"GetLogicalProcessorInformationEx failed (error {error})")
    return buffer.raw[: length.value]


def detect_physical_cores(
    *,
    platform: str = sys.platform,
    windows_info: Callable[[], bytes] = _windows_core_info,
    cpu_count: Callable[[], int | None] = os.cpu_count,
) -> int:
    """Physical core count; fallback `os.cpu_count() // 2`, else 0 (library default)."""
    reason = "not Windows"
    if platform == "win32":
        try:
            cores = count_core_records(windows_info())
        except (OSError, ValueError, AttributeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if cores > 0:
                logger.info("Whisper cpu_threads: %s physical cores detected", cores)
                return cores
            reason = "no core records"
    logical = cpu_count()
    if logical:
        fallback = max(logical // 2, 1)
        logger.warning(
            "Physical core detection unavailable (%s); Whisper cpu_threads = %s (%s logical / 2)",
            reason,
            fallback,
            logical,
        )
        return fallback
    logger.warning(
        "Physical core detection unavailable (%s) and CPU count unknown; "
        "Whisper uses the library default thread count",
        reason,
    )
    return LIBRARY_DEFAULT_THREADS


@lru_cache(maxsize=1)
def physical_cores() -> int:
    """`detect_physical_cores()` once per process (logged once)."""
    return detect_physical_cores()

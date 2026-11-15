"""Small atomic scheduler journal and process lock; no database schema changes."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.services.backups import BackupFailure, _directory, _plain

ErrorCode = Literal[
    "dependencies_unhealthy",
    "backup_failed",
    "interrupted",
    "state_unavailable",
    "retention_failed",
    "worker_unavailable",
    "archive_invalid",
    "backup_locked",
]


class ScheduleState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    due_at: AwareDatetime | None = None
    completed_due_at: AwareDatetime | None = None
    started_at: AwareDatetime | None = None
    checked_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    last_failure_at: AwareDatetime | None = None
    retry_at: AwareDatetime | None = None
    attempts: int = Field(default=0, ge=0, le=3)
    failed_attempts: int = Field(default=0, ge=0)
    archive_name: str | None = Field(default=None, pattern=r"^\d{8}T\d{12}Z-[a-f0-9]{32}$")
    running: bool = False
    error_code: ErrorCode | None = None
    last_error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def valid_claim(self) -> Self:
        if self.running and not (self.due_at and self.started_at and self.archive_name):
            raise ValueError("Incomplete running claim")
        if self.attempts and not (self.due_at and self.started_at and self.archive_name):
            raise ValueError("Incomplete attempted claim")
        if self.completed_due_at and (
            not self.due_at or self.completed_due_at > self.due_at or not self.last_success_at
        ):
            raise ValueError("Invalid completion")
        return self


def read_state(path: Path) -> ScheduleState:
    if not _plain(path):
        raise BackupFailure("Unsafe scheduler state")
    # Reject linked ancestors without creating directories in a status request.
    if any(not _plain(p) for p in path.parents):
        raise BackupFailure("Unsafe scheduler directory")
    if not path.exists():
        return ScheduleState()
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, dict) or set(data) != set(ScheduleState.model_fields):
        raise BackupFailure("Incomplete scheduler state")
    return ScheduleState.model_validate_json(content)


def write_state(path: Path, state: ScheduleState) -> None:
    _directory(path.parent)
    if not _plain(path):
        raise BackupFailure("Unsafe scheduler state")
    temporary = path.with_name(f".schedule-{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(state.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def schedule_lock(path: Path) -> Iterator[bool]:
    """Kernel-owned lock releases on process exit; never unlink the lock inode.

    M7-01's separate dump lock remains fail-closed after an interrupted subprocess.
    This avoids assuming a child pg_dump stopped just because its worker exited.
    """
    _directory(path.parent)
    if not _plain(path):
        raise BackupFailure("Unsafe scheduler lock")
    with path.open("a+b") as stream:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

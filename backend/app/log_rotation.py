"""Cooperating processes serialize append and rotation, closing files before unlock."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Self, override


@contextmanager
def rotation_lock(path: Path) -> Iterator[None]:
    # Permanent inode: deleting/replacing a lock file would split writer ownership.
    with path.open("a+b") as stream:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ProcessRotatingHandler(RotatingFileHandler):
    """Same numeric retention as stdlib; all app writers must use this handler.

    Opening inside the shared lock and closing before release avoids stale descriptors
    and Windows rename failures from another cooperating writer's open handle.
    """

    def __init__(
        self,
        filename: str | Path,
        *,
        maxBytes: int,  # noqa: N803 - stdlib keyword API
        backupCount: int,  # noqa: N803 - stdlib keyword API
        encoding: str = "utf-8",
        delay: bool = True,
    ) -> None:
        if not delay:
            raise ValueError("Process log writers require delayed opening")
        super().__init__(
            filename, maxBytes=maxBytes, backupCount=backupCount, encoding=encoding, delay=True
        )

    @override
    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, os.SEEK_END)
        size = self.stream.tell()
        message = self.format(record) + os.linesep
        return (
            self.maxBytes > 0
            and size > 0
            and (
                size + len(message.encode(self.encoding or "utf-8", errors="replace"))
                >= self.maxBytes
            )
        )

    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            with rotation_lock(Path(self.baseFilename + ".lock")):
                try:
                    # Base emit handles rollover errors through our sanitized handleError.
                    super().emit(record)
                finally:
                    if self.stream is not None:
                        self.stream.close()
                        self.stream = None
        except Exception:
            self.handleError(record)

    @override
    def handleError(self, record: logging.LogRecord) -> None:
        # Stdlib prints the original record/arguments and traceback, possibly secrets.
        # The console handler still displays the original event through redaction.
        sys.stderr.write(
            "Application log write/rotation failed; check disk, permissions and file locks.\n"
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

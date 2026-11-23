"""The cTrader token file: atomic writes and a lock shared by the API and worker processes.

`<data_dir>/ctrader_tokens.json` (gitignored). Refresh tokens are single use, so whoever
refreshes must hold `TokenStore.lock` from reading the old pair until the new one is on disk.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final

from pydantic import SecretStr

from app.ctrader.errors import CtraderError, CtraderErrorCode

logger = logging.getLogger(__name__)

TOKENS_FILE: Final = "ctrader_tokens.json"
_LOCK_SUFFIX: Final = ".lock"
LOCK_TIMEOUT_S: Final = 30.0
_LOCK_POLL_S: Final = 0.02
# Windows: os.replace fails while a reader has the target open; readers are brief.
_REPLACE_ATTEMPTS: Final = 5
_REPLACE_PAUSE_S: Final = 0.05


@dataclass(frozen=True)
class TokenPair:
    """``SecretStr`` keeps both tokens out of any repr or log."""

    access_token: SecretStr
    refresh_token: SecretStr
    expires_at: datetime  # aware UTC
    obtained_at: datetime  # aware UTC


def tokens_path(data_dir: Path) -> Path:
    return data_dir / TOKENS_FILE


def _try_lock(stream: IO[bytes]) -> bool:
    stream.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(stream: IO[bytes]) -> None:
    stream.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(UTC)


def _parse_pair(text: str) -> TokenPair:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    access, refresh = data.get("access_token"), data.get("refresh_token")
    if not (isinstance(access, str) and access and isinstance(refresh, str) and refresh):
        raise ValueError("tokens are missing")
    return TokenPair(
        SecretStr(access),
        SecretStr(refresh),
        _parse_time(data.get("expires_at")),
        _parse_time(data.get("obtained_at")),
    )


class TokenStore:
    def __init__(self, path: Path, *, lock_timeout_s: float = LOCK_TIMEOUT_S) -> None:
        self.path = path
        self._lock_path = path.with_name(path.name + _LOCK_SUFFIX)
        self._lock_timeout_s = lock_timeout_s

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive across processes and threads; ``timeout`` when it stays busy."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as stream:
            deadline = time.monotonic() + self._lock_timeout_s
            while not _try_lock(stream):
                if time.monotonic() >= deadline:
                    raise CtraderError(CtraderErrorCode.TIMEOUT, "token file is busy")
                time.sleep(_LOCK_POLL_S)
            try:
                yield
            finally:
                _unlock(stream)

    def read(self) -> TokenPair | None:
        """None when not connected. A broken file is ``token_invalid``; its text is not shown."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise CtraderError(
                CtraderErrorCode.TOKEN_STORE_FAILED,
                f"token file unreadable: {type(exc).__name__}",
            ) from None
        try:
            return _parse_pair(text)
        except (ValueError, TypeError):
            raise CtraderError(CtraderErrorCode.TOKEN_INVALID, "token file is damaged") from None

    def write(self, pair: TokenPair) -> None:
        """Atomic: the old file stays complete until the new one replaces it."""
        body = json.dumps(
            {
                "access_token": pair.access_token.get_secret_value(),
                "refresh_token": pair.refresh_token.get_secret_value(),
                "expires_at": pair.expires_at.astimezone(UTC).isoformat(),
                "obtained_at": pair.obtained_at.astimezone(UTC).isoformat(),
            }
        )
        temp: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp = tempfile.mkstemp(
                dir=self.path.parent, prefix=self.path.name, suffix=".tmp"
            )
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            self._replace(temp)
            temp = None
        except OSError as exc:
            logger.error("cTrader token file not written: %s", type(exc).__name__)
            raise CtraderError(
                CtraderErrorCode.TOKEN_STORE_FAILED, "could not write the token file"
            ) from None
        finally:
            if temp is not None:
                Path(temp).unlink(missing_ok=True)

    def _replace(self, temp: str) -> None:
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temp, self.path)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_PAUSE_S)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

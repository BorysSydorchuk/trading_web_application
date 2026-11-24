"""OAuth ``state`` values: random, single use, expiring, compared in constant time.

Held in the API process: a restart during the consent screen just means connecting again.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

STATE_TTL: Final = timedelta(minutes=10)
MAX_PENDING: Final = 16
_STATE_BYTES: Final = 32


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OAuthStateStore:
    def __init__(
        self, *, now: Callable[[], datetime] = _utc_now, max_pending: int = MAX_PENDING
    ) -> None:
        self._now = now
        self._max_pending = max_pending
        self._lock = threading.Lock()
        self._pending: dict[str, datetime] = {}  # insertion order = oldest first

    def issue(self) -> str:
        value = secrets.token_urlsafe(_STATE_BYTES)
        with self._lock:
            self._drop_expired()
            while len(self._pending) >= self._max_pending:
                del self._pending[next(iter(self._pending))]
            self._pending[value] = self._now() + STATE_TTL
        return value

    def consume(self, value: str) -> bool:
        """True once for a live state. A wrong value leaves the pending ones untouched."""
        candidate = value.encode("utf-8")
        with self._lock:
            self._drop_expired()
            match: str | None = None
            for known in self._pending:  # no early exit: constant time over the entries
                if hmac.compare_digest(known.encode("utf-8"), candidate):
                    match = known
            if match is None:
                return False
            del self._pending[match]
            return True

    def _drop_expired(self) -> None:
        now = self._now()
        for value in [v for v, expires in self._pending.items() if expires <= now]:
            del self._pending[value]

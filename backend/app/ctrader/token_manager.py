"""A valid access token, refreshed before expiry and serialized across processes."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pydantic import SecretStr

from app.ctrader import oauth
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.tokens import TokenPair, TokenStore

logger = logging.getLogger(__name__)

# expiresIn is about 30 days; a few days leave room for the app being off.
REFRESH_MARGIN: Final = timedelta(days=3)
# A refused refresh only heals by reconnecting: do not ask the token endpoint every cycle.
REFUSED_COOLDOWN: Final = timedelta(hours=1)
_TRANSIENT: Final = (CtraderErrorCode.CONNECTION_FAILED, CtraderErrorCode.TIMEOUT)
_WRITE_ATTEMPTS: Final = 3
_WRITE_PAUSE_S: Final = 0.1
_RECONNECT: Final = "cTrader refused the token refresh: reconnect required"


@dataclass
class _ProcessState:
    """Per token file, for this process. Accessed under the file lock."""

    unsaved: TokenPair | None = None  # refreshed, but the file could not be written
    refused_obtained_at: datetime | None = None  # identifies the refused pair, holds no secret
    refused_until: datetime | None = None


_states: dict[Path, _ProcessState] = {}
_states_guard: Final = threading.Lock()


def _state_for(path: Path) -> _ProcessState:
    with _states_guard:
        return _states.setdefault(path, _ProcessState())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TokenManager:
    def __init__(
        self,
        store: TokenStore,
        client_id: str,
        client_secret: SecretStr,
        *,
        http: oauth.TokenHttp = oauth.call_token_endpoint,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._now = now
        self._state = _state_for(store.path)

    def fresh_access_token(self) -> SecretStr:
        """The stored token, refreshed first when inside `REFRESH_MARGIN`.

        The file lock is held from reading the old pair until the new one is on disk, so a
        second process sees the new pair instead of burning the single-use refresh token.
        """
        with self._store.lock():
            pair = self._current_pair()
            if pair is None:
                raise CtraderError(CtraderErrorCode.TOKEN_INVALID, "cTrader is not connected")
            now = self._now()
            if pair.expires_at - now > REFRESH_MARGIN:
                return pair.access_token
            self._check_cooldown(pair, now)
            return self._refresh(pair, now)

    def _current_pair(self) -> TokenPair | None:
        """The file's pair, or a newer one this process could not save (saved again now).

        An empty file means the connection was forgotten, and a newer file a new connection:
        either way the unsaved pair is dropped and never written back.
        """
        unsaved = self._state.unsaved
        if unsaved is None:
            return self._store.read()
        try:
            disk = self._store.read()
        except CtraderError:
            disk = unsaved  # a damaged file: the pair in memory is the only good one
        if disk is None or disk.obtained_at > unsaved.obtained_at:
            self._state.unsaved = None
            return disk
        if self._save(unsaved):
            self._state.unsaved = None
        return unsaved

    def _check_cooldown(self, pair: TokenPair, now: datetime) -> None:
        state = self._state
        if (
            state.refused_until is not None
            and state.refused_obtained_at == pair.obtained_at
            and now <= state.refused_until
        ):
            raise CtraderError(CtraderErrorCode.TOKEN_INVALID, _RECONNECT)

    def _save(self, pair: TokenPair) -> bool:
        for attempt in range(_WRITE_ATTEMPTS):
            try:
                self._store.write(pair)
                return True
            except CtraderError as exc:
                logger.error("cTrader token pair not saved: %s", exc.code.value)
                if attempt < _WRITE_ATTEMPTS - 1:
                    time.sleep(_WRITE_PAUSE_S)
        return False

    def _refresh(self, pair: TokenPair, now: datetime) -> SecretStr:
        try:
            new = oauth.refresh_tokens(
                pair.refresh_token,
                self._client_id,
                self._client_secret,
                http=self._http,
                now=now,
            )
        except CtraderError as exc:
            if exc.code in _TRANSIENT and pair.expires_at > now:
                logger.warning("cTrader token refresh postponed: %s", exc.code.value)
                return pair.access_token
            logger.error("cTrader token refresh failed: %s", exc.code.value)
            if exc.code is CtraderErrorCode.TOKEN_INVALID:
                self._state.refused_obtained_at = pair.obtained_at
                self._state.refused_until = now + REFUSED_COOLDOWN
                raise CtraderError(CtraderErrorCode.TOKEN_INVALID, _RECONNECT) from None
            raise
        self._state.refused_obtained_at = self._state.refused_until = None
        # The old pair is dead now: if the file cannot be written, keep the new one in memory.
        if not self._save(new):
            self._state.unsaved = new
            logger.error("cTrader token pair kept in memory; saving is retried on each use")
        logger.info("cTrader token refreshed, valid until %s", new.expires_at.isoformat())
        return new.access_token

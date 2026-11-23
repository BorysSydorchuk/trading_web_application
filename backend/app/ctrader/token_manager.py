"""A valid access token, refreshed before expiry and serialized across processes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import SecretStr

from app.ctrader import oauth
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.tokens import TokenPair, TokenStore

logger = logging.getLogger(__name__)

# expiresIn is about 30 days; a few days leave room for the app being off.
REFRESH_MARGIN: Final = timedelta(days=3)
_TRANSIENT: Final = (CtraderErrorCode.CONNECTION_FAILED, CtraderErrorCode.TIMEOUT)


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

    def fresh_access_token(self) -> SecretStr:
        """The stored token, refreshed first when inside `REFRESH_MARGIN`.

        The file lock is held from reading the old pair until the new one is on disk, so a
        second process sees the new pair instead of burning the single-use refresh token.
        """
        with self._store.lock():
            pair = self._store.read()
            if pair is None:
                raise CtraderError(CtraderErrorCode.TOKEN_INVALID, "cTrader is not connected")
            now = self._now()
            if pair.expires_at - now > REFRESH_MARGIN:
                return pair.access_token
            return self._refresh(pair, now)

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
            raise
        self._store.write(new)  # before anything can use the new token
        logger.info("cTrader token refreshed, valid until %s", new.expires_at.isoformat())
        return new.access_token

"""Typed cTrader errors with the stable codes stored in `sync_log` and shown by the UI.

Messages are short English text. Everything that may echo server text passes through
`mask_secrets` with the secrets known at the raise site.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Final

from app.mt5.errors import mask_secrets

_MAX_DESCRIPTION: Final = 200


class CtraderErrorCode(enum.StrEnum):
    NOT_CONFIGURED = "not_configured"
    TOKEN_EXPIRED = "token_expired"  # noqa: S105 - error code, not a secret
    TOKEN_INVALID = "token_invalid"  # noqa: S105 - error code, not a secret
    TOKEN_STORE_FAILED = "token_store_failed"  # noqa: S105 - error code, not a secret
    NOT_AUTHORIZED = "not_authorized"
    CLIENT_AUTH_FAILED = "client_auth_failed"
    CONNECTION_FAILED = "connection_failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    TRADE_SCOPE_REFUSED = "trade_scope_refused"
    BAD_RESPONSE = "bad_response"
    ACCOUNT_DISCONNECTED = "account_disconnected"
    EQUITY_UNAVAILABLE = "equity_unavailable"
    HISTORY_INCOMPLETE = "history_incomplete"
    STATE_INVALID = "state_invalid"
    ACCESS_DENIED = "access_denied"
    INTERNAL_ERROR = "internal_error"


_SERVER_CODES: Final[dict[str, CtraderErrorCode]] = {
    "CH_ACCESS_TOKEN_INVALID": CtraderErrorCode.TOKEN_INVALID,
    "OA_AUTH_TOKEN_EXPIRED": CtraderErrorCode.TOKEN_EXPIRED,
    "ACCOUNT_NOT_AUTHORIZED": CtraderErrorCode.NOT_AUTHORIZED,
    "CH_CTID_TRADER_ACCOUNT_NOT_FOUND": CtraderErrorCode.NOT_AUTHORIZED,
    "CH_CLIENT_AUTH_FAILURE": CtraderErrorCode.CLIENT_AUTH_FAILED,
    "CH_CLIENT_NOT_AUTHENTICATED": CtraderErrorCode.CLIENT_AUTH_FAILED,
    "REQUEST_FREQUENCY_EXCEEDED": CtraderErrorCode.RATE_LIMITED,
    "BLOCKED_PAYLOAD_TYPE": CtraderErrorCode.RATE_LIMITED,
    "SERVER_IS_UNDER_MAINTENANCE": CtraderErrorCode.CONNECTION_FAILED,
    "CH_SERVER_NOT_REACHABLE": CtraderErrorCode.CONNECTION_FAILED,
}


class CtraderError(Exception):
    """A cTrader failure with a stable ``code``; ``message`` is safe to log and show."""

    def __init__(
        self,
        code: CtraderErrorCode,
        message: str,
        *,
        retry_after: float | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        self.code = CtraderErrorCode(code)
        self.message = mask_secrets(message, secrets)
        self.retry_after = retry_after
        super().__init__(f"{self.code}: {self.message}")


def error_from_server(
    server_code: str,
    description: object,
    retry_after: float | None,
    *,
    secrets: Iterable[str] = (),
) -> CtraderError:
    """Map an ErrorRes to a `CtraderError`; an unknown code is a visible ``bad_response``."""
    kind = _SERVER_CODES.get(server_code, CtraderErrorCode.BAD_RESPONSE)
    text = (
        mask_secrets(str(description), secrets)[:_MAX_DESCRIPTION]
        if description
        else "no description"
    )
    return CtraderError(
        kind, f"cTrader {server_code}: {text}", retry_after=retry_after, secrets=secrets
    )

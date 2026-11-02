"""Typed MT5 errors with the stable codes used by sync status (docs/api.md, PRD 6.2).

`Mt5Error.code` is what the worker stores in `sync_log` and the UI maps to Ukrainian text.
Messages are short English text and never contain a password: every message passes
through `mask_secrets` with the secrets known at the raise site.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable

MASK = "***"


class Mt5ErrorCode(enum.StrEnum):
    PASSWORD_MISSING = "password_missing"  # noqa: S105 - error code, not a secret
    TERMINAL_NOT_FOUND = "terminal_not_found"
    TERMINAL_START_FAILED = "terminal_start_failed"
    LOGIN_FAILED = "login_failed"
    TIMEOUT = "timeout"
    MT5_ERROR = "mt5_error"


# MetaTrader5 package result codes (MetaTrader5/__init__.py, RES_*).
RES_S_OK = 1
RES_E_FAIL = -1
RES_E_INVALID_PARAMS = -2
RES_E_NOT_FOUND = -4  # "no history"
RES_E_INVALID_VERSION = -5
RES_E_AUTH_FAILED = -6
RES_E_INTERNAL_FAIL = -10000
RES_E_INTERNAL_FAIL_SEND = -10001
RES_E_INTERNAL_FAIL_RECEIVE = -10002
RES_E_INTERNAL_FAIL_INIT = -10003
RES_E_INTERNAL_FAIL_CONNECT = -10004
RES_E_INTERNAL_FAIL_TIMEOUT = -10005

# IPC hiccups during a read: safe to retry a read-only call once.
TRANSIENT_CODES = frozenset(
    {RES_E_INTERNAL_FAIL, RES_E_INTERNAL_FAIL_SEND, RES_E_INTERNAL_FAIL_RECEIVE}
)
# "Nothing there" answers: an optional read returns None / an empty list.
EMPTY_CODES = frozenset({RES_S_OK, RES_E_NOT_FOUND})
_START_CODES = frozenset(
    {
        RES_E_FAIL,
        RES_E_INVALID_VERSION,
        RES_E_INTERNAL_FAIL,
        RES_E_INTERNAL_FAIL_SEND,
        RES_E_INTERNAL_FAIL_RECEIVE,
        RES_E_INTERNAL_FAIL_INIT,
        RES_E_INTERNAL_FAIL_CONNECT,
    }
)


def mask_secrets(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, MASK)
    return text


class Mt5Error(Exception):
    """An MT5 failure with a stable ``code``; ``message`` is safe to log and show."""

    def __init__(
        self,
        code: Mt5ErrorCode,
        message: str,
        *,
        mt5_code: int | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        self.code = Mt5ErrorCode(code)
        self.message = mask_secrets(message, secrets)
        self.mt5_code = mt5_code
        super().__init__(f"{self.code}: {self.message}")


def split_last_error(last_error: object) -> tuple[int, str]:
    """``mt5.last_error()`` -> (code, message); tolerant of odd shapes."""
    if isinstance(last_error, tuple | list) and len(last_error) >= 2:
        try:
            return int(last_error[0]), str(last_error[1])
        except (TypeError, ValueError):
            pass
    return RES_E_FAIL, str(last_error)


def error_from_last_error(
    last_error: object, *, during: str, secrets: Iterable[str] = ()
) -> Mt5Error:
    """Map an MT5 ``last_error()`` to an `Mt5Error`. ``during="initialize"`` for connect."""
    code, message = split_last_error(last_error)
    kind = Mt5ErrorCode.MT5_ERROR
    if code == RES_E_AUTH_FAILED:
        kind = Mt5ErrorCode.LOGIN_FAILED
    elif code == RES_E_INTERNAL_FAIL_TIMEOUT:
        kind = Mt5ErrorCode.TIMEOUT
    elif during == "initialize" and code in _START_CODES:
        # e.g. (-10003, "IPC initialize failed, MetaTrader 5 x64 not found")
        not_found = "not found" in message.lower()
        kind = Mt5ErrorCode.TERMINAL_NOT_FOUND if not_found else Mt5ErrorCode.TERMINAL_START_FAILED
    text = f"{during} failed: {message} (MT5 {code})"
    return Mt5Error(kind, text, mt5_code=code, secrets=secrets)

"""The read-only guarantee of the cTrader client.

`assert_allowed` runs in the single send function (`CtraderConnection._send`) and raises
before anything is written. Only the types in ``ALLOWED_OUTGOING`` can leave the app; the
blocklist exists so the guard tests can name what must never appear. This is the only file
in the package that may mention a trading message.
"""

from __future__ import annotations

from typing import Final

ALLOWED_OUTGOING: Final = frozenset(
    {
        51,  # heartbeat
        2100,  # ApplicationAuthReq
        2102,  # AccountAuthReq
        2114,  # SymbolsListReq (symbol names)
        2116,  # SymbolByIdReq (digits, lot size)
        2121,  # TraderReq
        2124,  # ReconcileReq (open positions)
        2133,  # DealListReq (deal history)
        2149,  # GetAccountListByAccessTokenReq
        2187,  # GetPositionUnrealizedPnLReq
    }
)

BLOCKED_OUTGOING: Final = frozenset(
    {
        2106,  # NewOrderReq
        2108,  # CancelOrderReq
        2109,  # AmendOrderReq
        2110,  # AmendPositionSLTPReq
        2111,  # ClosePositionReq
    }
)


class ForbiddenMessageError(RuntimeError):
    """A message outside the read-only allowlist. A programming error, never retried."""


def assert_allowed(payload_type: object) -> None:
    """Raise unless ``payload_type`` is an exact int on the allowlist."""
    if type(payload_type) is not int or payload_type not in ALLOWED_OUTGOING:
        raise ForbiddenMessageError(f"cTrader payload type {payload_type!r} is not allowed")

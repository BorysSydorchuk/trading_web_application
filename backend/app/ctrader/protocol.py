"""cTrader Open API JSON protocol: payload types, limits and the message envelope.

Payload types are from https://help.ctrader.com/open-api/model-messages/ (ProtoOAPayloadType)
and common-model-messages (ProtoPayloadType). What may be SENT is decided by `guard`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

# Outgoing (each one is on the guard's allowlist).
HEARTBEAT: Final = 51
APPLICATION_AUTH_REQ: Final = 2100
ACCOUNT_AUTH_REQ: Final = 2102
ASSET_LIST_REQ: Final = 2112
SYMBOLS_LIST_REQ: Final = 2114
SYMBOL_BY_ID_REQ: Final = 2116
TRADER_REQ: Final = 2121
RECONCILE_REQ: Final = 2124
DEAL_LIST_REQ: Final = 2133
TRENDBARS_REQ: Final = 2137
TICK_DATA_REQ: Final = 2145
ORDER_LIST_BY_POSITION_REQ: Final = 2183
ACCOUNT_LIST_REQ: Final = 2149
POSITION_PNL_REQ: Final = 2187

# Incoming responses.
COMMON_ERROR_RES: Final = 50
APPLICATION_AUTH_RES: Final = 2101
ACCOUNT_AUTH_RES: Final = 2103
ASSET_LIST_RES: Final = 2113
SYMBOLS_LIST_RES: Final = 2115
SYMBOL_BY_ID_RES: Final = 2117
TRADER_RES: Final = 2122
RECONCILE_RES: Final = 2125
DEAL_LIST_RES: Final = 2134
TRENDBARS_RES: Final = 2138
TICK_DATA_RES: Final = 2146
ORDER_LIST_BY_POSITION_RES: Final = 2184
ACCOUNT_LIST_RES: Final = 2150
POSITION_PNL_RES: Final = 2188
ERROR_RES: Final = 2142

# Incoming events.
ACCOUNTS_TOKEN_INVALIDATED_EVENT: Final = 2147
CLIENT_DISCONNECT_EVENT: Final = 2148
ACCOUNT_DISCONNECT_EVENT: Final = 2164

LIVE_ENDPOINT: Final = "wss://live.ctraderapi.com:5036"
DEMO_ENDPOINT: Final = "wss://demo.ctraderapi.com:5036"

HEARTBEAT_INTERVAL_S: Final = 10
# TO VERIFY ON THE FIRST LIVE CHECK: the docs do not show the JSON heartbeat body.
HEARTBEAT_PAYLOAD: Final[dict[str, Any]] = {}

MAX_REQUESTS_PER_S: Final = 50
MAX_HISTORICAL_REQUESTS_PER_S: Final = 5
# DealListReq: the server refuses a wider fromTimestamp..toTimestamp range (one week).
MAX_DEAL_WINDOW_MS: Final = 604_800_000


@dataclass(frozen=True)
class Frame:
    """One decoded message. ``repr`` hides the payload: it can hold an access token."""

    payload_type: int
    payload: dict[str, Any]
    client_msg_id: str | None

    def __repr__(self) -> str:
        return f"Frame(payload_type={self.payload_type})"


def encode_frame(client_msg_id: str, payload_type: int, payload: dict[str, Any]) -> str:
    return json.dumps(
        {"clientMsgId": client_msg_id, "payloadType": payload_type, "payload": payload},
        separators=(",", ":"),
    )


def decode_frame(raw: str | bytes) -> Frame:
    """Raises ValueError on anything that is not a well-formed envelope."""
    data = json.loads(raw)
    if not isinstance(data, dict) or type(data.get("payloadType")) is not int:
        raise ValueError("not a cTrader envelope")
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("cTrader payload is not an object")
    msg_id = data.get("clientMsgId")
    return Frame(data["payloadType"], payload, msg_id if isinstance(msg_id, str) else None)

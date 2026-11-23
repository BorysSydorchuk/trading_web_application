"""Test doubles for the cTrader client: no socket and no HTTP call ever leaves the test."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.ctrader import protocol as p
from app.models import Account

Reply = tuple[int, dict[str, Any]] | None
Handler = Reply | Callable[[dict[str, Any]], Reply]

CLIENT_ID = "client-id-synthetic"
CLIENT_SECRET = "client-secret-synthetic-XYZ"  # noqa: S105 - synthetic
ACCESS_TOKEN = "access-token-synthetic-AAA"  # noqa: S105 - synthetic
REFRESH_TOKEN = "refresh-token-synthetic-BBB"  # noqa: S105 - synthetic
CTID = 7001
TRADER_LOGIN = 5100200


def default_handlers() -> dict[int, Handler]:
    """A healthy server: one demo account, balance 1000.50, one position at +12.34."""
    return {
        p.APPLICATION_AUTH_REQ: (p.APPLICATION_AUTH_RES, {}),
        p.ACCOUNT_AUTH_REQ: (p.ACCOUNT_AUTH_RES, {"ctidTraderAccountId": CTID}),
        p.TRADER_REQ: (
            p.TRADER_RES,
            {
                "ctidTraderAccountId": CTID,
                "trader": {"ctidTraderAccountId": CTID, "balance": 100050, "moneyDigits": 2},
            },
        ),
        p.POSITION_PNL_REQ: (
            p.POSITION_PNL_RES,
            {
                "ctidTraderAccountId": CTID,
                "moneyDigits": 2,
                "positionUnrealizedPnL": [
                    {"positionId": 1, "grossUnrealizedPnL": 1300, "netUnrealizedPnL": 1234}
                ],
            },
        ),
        p.ACCOUNT_LIST_REQ: (p.ACCOUNT_LIST_RES, account_list_payload()),
    }


def account_list_payload(scope: object = "SCOPE_VIEW") -> dict[str, Any]:
    return {
        "accessToken": ACCESS_TOKEN,
        "permissionScope": scope,
        "ctidTraderAccount": [
            {
                "ctidTraderAccountId": CTID,
                "isLive": False,
                "traderLogin": TRADER_LOGIN,
                "brokerTitleShort": "Demo Broker",
            }
        ],
    }


class FakeTransport:
    """Answers each sent frame from ``handlers``; records what was sent."""

    def __init__(self, handlers: Mapping[int, Handler] | None = None) -> None:
        self.handlers: dict[int, Handler] = dict(
            default_handlers() if handlers is None else handlers
        )
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._inbox: asyncio.Queue[str | Exception] = asyncio.Queue()

    def types_sent(self) -> list[int]:
        return [int(frame["payloadType"]) for frame in self.sent]

    def push(self, payload_type: int, payload: dict[str, Any], msg_id: str | None = None) -> None:
        frame: dict[str, Any] = {"payloadType": payload_type, "payload": payload}
        if msg_id is not None:
            frame["clientMsgId"] = msg_id
        self._inbox.put_nowait(json.dumps(frame))

    def push_raw(self, item: str | Exception) -> None:
        self._inbox.put_nowait(item)

    async def send(self, data: str) -> None:
        frame = json.loads(data)
        self.sent.append(frame)
        handler = self.handlers.get(int(frame["payloadType"]))
        reply = handler(frame) if callable(handler) else handler
        if reply is not None:
            self.push(reply[0], reply[1], frame.get("clientMsgId"))

    async def recv(self) -> str:
        item = await self._inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class FakeConnector:
    """``Connector`` handing out prepared transports; an Exception entry fails that attempt."""

    def __init__(self, *transports: FakeTransport | Exception) -> None:
        self._queue = list(transports)
        self.urls: list[str] = []

    async def __call__(self, url: str) -> FakeTransport:
        self.urls.append(url)
        item = self._queue.pop(0) if len(self._queue) > 1 else self._queue[0]
        if isinstance(item, Exception):
            raise item
        return item


async def no_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


def make_ctrader_account(session: Session, **overrides: Any) -> Account:
    values: dict[str, Any] = {
        "name": "cTrader Demo",
        "firm": "Firm",
        "program": "Program",
        "phase": "phase_1",
        "login": TRADER_LOGIN,
        "server": "Demo Broker",
        "terminal_path": None,
        "starting_balance": Decimal("1000.00"),
        "currency": "USD",
        "platform": "ctrader",
        "ctid_trader_account_id": CTID,
        "ctrader_is_live": False,
    }
    account = Account(**(values | overrides))
    session.add(account)
    session.commit()
    return account


def make_mt5_account(session: Session, **overrides: Any) -> Account:
    values: dict[str, Any] = {
        "name": "MT5 Account",
        "firm": "Firm",
        "program": "Program",
        "phase": "phase_1",
        "login": 90000001,
        "server": "Broker-Server",
        "terminal_path": "D:\\MT5\\one\\terminal64.exe",
        "starting_balance": Decimal("1000.00"),
        "currency": "USD",
    }
    account = Account(**(values | overrides))
    session.add(account)
    session.commit()
    return account

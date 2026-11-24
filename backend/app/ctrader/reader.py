"""Read-only operations on top of a connection: account list, balance and equity."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from pydantic import SecretStr

from app.ctrader import protocol as p
from app.ctrader.connection import Connector, CtraderConnection, Sleep, open_websocket
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.money import equity_from, parse_int, scale_money

logger = logging.getLogger(__name__)

_SCOPE_VIEW_NAME: Final = "SCOPE_VIEW"
_SCOPE_VIEW_VALUE: Final = 0
_DEFAULT_BROKER: Final = "cTrader"
_MAX_BROKER: Final = 100  # accounts.server is String(100)
_RETRY_READ: Final = (CtraderErrorCode.ACCOUNT_DISCONNECTED, CtraderErrorCode.CONNECTION_FAILED)
# Not an equity problem: the account itself needs attention («Підключіть cTrader знову»).
_NOT_EQUITY: Final = (CtraderErrorCode.TOKEN_INVALID, CtraderErrorCode.TOKEN_EXPIRED)
# accounts.login is BIGINT; a larger login is treated as missing (account_incomplete).
_MAX_LOGIN: Final = 2**63 - 1
_BALANCE_CHANGED: Final = "balance_changed"
_CONSISTENCY_ATTEMPTS: Final = 2
# Below the worker's 60 s schedule; closing the connections adds a few seconds at most.
READ_BUDGET_S: Final = 45.0


@dataclass(frozen=True)
class Credentials:
    """App id/secret + access token. ``SecretStr`` keeps both out of any repr."""

    client_id: str
    client_secret: SecretStr
    access_token: SecretStr

    def secrets(self) -> tuple[str, str]:
        return self.client_secret.get_secret_value(), self.access_token.get_secret_value()


@dataclass(frozen=True)
class CtidAccount:
    ctid: int
    is_live: bool
    trader_login: int | None
    broker: str


@dataclass(frozen=True)
class AccountGrant:
    """2149's answer. ``view_only`` is True only for an explicit SCOPE_VIEW."""

    view_only: bool
    accounts: tuple[CtidAccount, ...]


@dataclass(frozen=True)
class BalanceRead:
    balance: Decimal
    equity: Decimal | None  # None: the P&L read failed, equity is unknown
    equity_error: str | None = None


def endpoint_for(is_live: bool) -> str:
    return p.LIVE_ENDPOINT if is_live else p.DEMO_ENDPOINT


async def authorize_app(connection: CtraderConnection, creds: Credentials) -> None:
    await connection.request(
        p.APPLICATION_AUTH_REQ,
        {"clientId": creds.client_id, "clientSecret": creds.client_secret.get_secret_value()},
        p.APPLICATION_AUTH_RES,
    )


def _check_account(payload: dict[str, Any], ctid: int) -> None:
    """Money from another account's answer must never be stored."""
    if (
        "ctidTraderAccountId" in payload
        and parse_int(payload["ctidTraderAccountId"], "ctidTraderAccountId") != ctid
    ):
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "answer for another account")


def _is_view_scope(scope: object) -> bool:
    return scope == _SCOPE_VIEW_NAME or (type(scope) is int and scope == _SCOPE_VIEW_VALUE)


def _login(raw: object) -> int | None:
    value = parse_int(raw, "traderLogin") if raw is not None else None
    return value if value is not None and value <= _MAX_LOGIN else None


def _parse_account(entry: object) -> CtidAccount:
    if not isinstance(entry, dict):
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "account entry is not an object")
    login = entry.get("traderLogin")
    broker = entry.get("brokerTitleShort")
    title = broker.strip()[:_MAX_BROKER] if isinstance(broker, str) else ""
    return CtidAccount(
        ctid=parse_int(entry.get("ctidTraderAccountId"), "ctidTraderAccountId"),
        is_live=entry.get("isLive") is True,  # optional in the docs: absent = not live
        trader_login=_login(login),
        broker=title or _DEFAULT_BROKER,
    )


async def fetch_account_list(
    creds: Credentials,
    connector: Connector = open_websocket,
    *,
    sleep: Sleep = asyncio.sleep,
    live: bool = True,
) -> AccountGrant:
    """The accounts granted to the token and its scope (either host answers 2149)."""
    connection = CtraderConnection(
        endpoint_for(live), connector, sleep=sleep, secrets=creds.secrets()
    )
    await connection.start()
    try:
        await authorize_app(connection, creds)
        payload = await connection.request(
            p.ACCOUNT_LIST_REQ,
            {"accessToken": creds.access_token.get_secret_value()},
            p.ACCOUNT_LIST_RES,
        )
    finally:
        await connection.close()
    entries = payload.get("ctidTraderAccount", [])
    if not isinstance(entries, list):
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "account list is not a list")
    return AccountGrant(
        view_only=_is_view_scope(payload.get("permissionScope")),
        accounts=tuple(_parse_account(entry) for entry in entries),
    )


def _field(item: object, name: str) -> object:
    return item.get(name) if isinstance(item, dict) else None


async def _read_net_pnl(connection: CtraderConnection, ctid: int) -> list[Decimal]:
    payload = await connection.request(
        p.POSITION_PNL_REQ, {"ctidTraderAccountId": ctid}, p.POSITION_PNL_RES
    )
    _check_account(payload, ctid)
    digits = parse_int(payload.get("moneyDigits"), "moneyDigits")
    positions = payload.get("positionUnrealizedPnL", [])
    if not isinstance(positions, list):
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "positions are not a list")
    return [
        scale_money(parse_int(_field(item, "netUnrealizedPnL"), "netUnrealizedPnL"), digits)
        for item in positions
    ]


async def _read_trader_balance(connection: CtraderConnection, ctid: int) -> Decimal:
    answer = await connection.request(p.TRADER_REQ, {"ctidTraderAccountId": ctid}, p.TRADER_RES)
    _check_account(answer, ctid)
    trader = answer.get("trader")
    if not isinstance(trader, dict):
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "trader is missing")
    _check_account(trader, ctid)
    digits = parse_int(trader.get("moneyDigits"), "moneyDigits")  # never assume a scale
    return scale_money(parse_int(trader.get("balance"), "balance"), digits)


async def _read_consistent(connection: CtraderConnection, ctid: int) -> BalanceRead:
    """2121, 2187, 2121: the P&L counts only if the balance did not move around it.

    A deal closing mid-read would otherwise add its profit twice (in the balance and in the
    P&L) or not at all. One retry, then equity is reported as unavailable.
    """
    balance = Decimal(0)
    for _attempt in range(_CONSISTENCY_ATTEMPTS):
        before = await _read_trader_balance(connection, ctid)
        try:
            net = await _read_net_pnl(connection, ctid)
        except CtraderError as exc:
            if exc.code in _RETRY_READ or exc.code in _NOT_EQUITY:
                raise
            logger.warning("cTrader account %s: equity not read: %s", ctid, exc.code.value)
            return BalanceRead(before, None, exc.code.value)
        balance = await _read_trader_balance(connection, ctid)
        if balance == before:
            return BalanceRead(balance, equity_from(balance, net))
    logger.warning("cTrader account %s: balance kept changing during the read", ctid)
    return BalanceRead(balance, None, _BALANCE_CHANGED)


async def read_balance(connection: CtraderConnection, creds: Credentials, ctid: int) -> BalanceRead:
    """Account auth, then a consistent balance and equity (see `money.equity_from`).

    A failed P&L read gives ``equity=None``: an equity is never invented. A dropped session
    is raised so the caller can authorize again.
    """
    auth = await connection.request(
        p.ACCOUNT_AUTH_REQ,
        {"ctidTraderAccountId": ctid, "accessToken": creds.access_token.get_secret_value()},
        p.ACCOUNT_AUTH_RES,
    )
    _check_account(auth, ctid)
    return await _read_consistent(connection, ctid)


class _EnvironmentDownError(Exception):
    """A reconnect failed: the other accounts of this environment would only wait for it."""

    def __init__(self, error: CtraderError) -> None:
        super().__init__(error.code.value)
        self.error = error


async def _restore_session(connection: CtraderConnection, creds: Credentials) -> None:
    try:
        await connection.reconnect()
        await authorize_app(connection, creds)
    except CtraderError as exc:
        raise _EnvironmentDownError(exc) from None


async def _read_one(
    connection: CtraderConnection, creds: Credentials, ctid: int
) -> BalanceRead | CtraderError:
    """One retry after a dropped account session or connection; errors are returned."""
    try:
        for attempt in range(2):
            try:
                return await read_balance(connection, creds, ctid)
            except CtraderError as exc:
                if attempt == 1 or exc.code not in _RETRY_READ:
                    raise
                if exc.code is CtraderErrorCode.CONNECTION_FAILED:
                    await _restore_session(connection, creds)
    except CtraderError as exc:
        return exc
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, "no read")  # pragma: no cover


async def _read_environment(
    creds: Credentials,
    is_live: bool,
    ctids: Sequence[int],
    connector: Connector,
    sleep: Sleep,
    budget_s: float,
) -> dict[int, BalanceRead | CtraderError]:
    """Accounts read before a failure or the time limit keep their results."""
    connection = CtraderConnection(
        endpoint_for(is_live), connector, sleep=sleep, secrets=creds.secrets()
    )
    results: dict[int, BalanceRead | CtraderError] = {}
    try:
        async with asyncio.timeout(budget_s):
            await connection.start()
            await authorize_app(connection, creds)
            for ctid in ctids:
                results[ctid] = await _read_one(connection, creds, ctid)
        return results
    except _EnvironmentDownError as exc:
        error = exc.error
    except TimeoutError:
        error = CtraderError(CtraderErrorCode.TIMEOUT, "cTrader read exceeded the time limit")
    except CtraderError as exc:
        error = exc
    finally:
        await connection.close()
    return {ctid: results.get(ctid, error) for ctid in ctids}


async def read_balances(
    creds: Credentials,
    targets: Sequence[tuple[int, bool]],
    connector: Connector = open_websocket,
    *,
    sleep: Sleep = asyncio.sleep,
    budget_s: float = READ_BUDGET_S,
) -> dict[int, BalanceRead | CtraderError]:
    """``(ctid, is_live)`` -> result. Live and demo run on their own connection, and an
    unexpected failure of one never loses the results of the other."""
    groups: dict[bool, list[int]] = {}
    for ctid, is_live in targets:
        groups.setdefault(is_live, []).append(ctid)
    parts = await asyncio.gather(
        *(
            _read_environment(creds, is_live, ctids, connector, sleep, budget_s)
            for is_live, ctids in groups.items()
        ),
        return_exceptions=True,
    )
    merged: dict[int, BalanceRead | CtraderError] = {}
    for ctids, part in zip(groups.values(), parts, strict=True):
        if isinstance(part, BaseException):
            if not isinstance(part, Exception):
                raise part  # cancellation
            logger.error("cTrader environment read failed: %s", type(part).__name__)
            error = CtraderError(CtraderErrorCode.INTERNAL_ERROR, "unexpected error, see log")
            merged.update(dict.fromkeys(ctids, error))
        else:
            merged.update(part)
    return merged

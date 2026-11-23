"""cTrader connection: envelope, heartbeat, reconnect, rate limits, server events, reads."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection, backoff_delays
from app.ctrader.errors import CtraderError, CtraderErrorCode, error_from_server
from app.ctrader.rate_limit import RateLimiter
from app.ctrader.reader import (
    Credentials,
    endpoint_for,
    fetch_account_list,
    read_balance,
    read_balances,
)
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    CTID,
    TRADER_LOGIN,
    FakeConnector,
    FakeTransport,
    account_list_payload,
    default_handlers,
    no_sleep,
)

CREDS = Credentials(CLIENT_ID, SecretStr(CLIENT_SECRET), SecretStr(ACCESS_TOKEN))


def _with_connection[T](
    transport: FakeTransport, body: Callable[[CtraderConnection], Awaitable[T]], **kwargs: Any
) -> T:
    async def scenario() -> T:
        connection = CtraderConnection(
            "wss://fake", FakeConnector(transport), sleep=no_sleep, **kwargs
        )
        await connection.start()
        try:
            return await body(connection)
        finally:
            await connection.close()

    return asyncio.run(scenario())


def _code(caught: pytest.ExceptionInfo[CtraderError]) -> CtraderErrorCode:
    return caught.value.code


def test_endpoints_by_environment() -> None:
    assert endpoint_for(True) == "wss://live.ctraderapi.com:5036"
    assert endpoint_for(False) == "wss://demo.ctraderapi.com:5036"


def test_request_uses_the_json_envelope() -> None:
    transport = FakeTransport()
    result = _with_connection(
        transport,
        lambda c: c.request(p.APPLICATION_AUTH_REQ, {"clientId": "x"}, p.APPLICATION_AUTH_RES),
    )
    assert result == {}
    frame = transport.sent[0]
    assert set(frame) == {"clientMsgId", "payloadType", "payload"}
    assert isinstance(frame["clientMsgId"], str)
    assert frame["payloadType"] == p.APPLICATION_AUTH_REQ


def test_heartbeat_is_sent_periodically() -> None:
    transport = FakeTransport({})

    async def wait(_: CtraderConnection) -> None:
        for _attempt in range(200):
            if p.HEARTBEAT in transport.types_sent():
                return
            await asyncio.sleep(0.005)

    _with_connection(transport, wait, heartbeat_s=0.01)
    beat = next(f for f in transport.sent if f["payloadType"] == p.HEARTBEAT)
    assert beat["payload"] == {}


def test_default_heartbeat_is_ten_seconds() -> None:
    assert p.HEARTBEAT_INTERVAL_S == 10


def test_backoff_is_exponential_and_capped() -> None:
    assert backoff_delays(6, base=1.0, cap=8.0) == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_open_retries_with_backoff_then_succeeds() -> None:
    transport = FakeTransport({})
    connector = FakeConnector(OSError("down"), OSError("down"), transport)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    async def scenario() -> None:
        connection = CtraderConnection("wss://fake", connector, sleep=sleep)
        await connection.start()
        await connection.close()

    asyncio.run(scenario())
    assert len(connector.urls) == 3
    assert slept == [1.0, 2.0]


def test_open_gives_up_with_connection_failed() -> None:
    connector = FakeConnector(OSError("secret-free failure"))

    async def scenario() -> None:
        await CtraderConnection("wss://fake", connector, sleep=no_sleep).start()

    with pytest.raises(CtraderError) as caught:
        asyncio.run(scenario())
    assert _code(caught) is CtraderErrorCode.CONNECTION_FAILED


def test_request_timeout() -> None:
    transport = FakeTransport({p.TRADER_REQ: None})
    with pytest.raises(CtraderError) as caught:
        _with_connection(
            transport,
            lambda c: c.request(p.TRADER_REQ, {}, p.TRADER_RES),
            request_timeout_s=0.01,
        )
    assert _code(caught) is CtraderErrorCode.TIMEOUT


def test_unexpected_response_type_is_refused() -> None:
    transport = FakeTransport({p.TRADER_REQ: (p.ACCOUNT_AUTH_RES, {})})
    with pytest.raises(CtraderError) as caught:
        _with_connection(transport, lambda c: c.request(p.TRADER_REQ, {}, p.TRADER_RES))
    assert _code(caught) is CtraderErrorCode.BAD_RESPONSE


@pytest.mark.parametrize(
    ("server_code", "expected"),
    [
        ("CH_ACCESS_TOKEN_INVALID", CtraderErrorCode.TOKEN_INVALID),
        ("OA_AUTH_TOKEN_EXPIRED", CtraderErrorCode.TOKEN_EXPIRED),
        ("ACCOUNT_NOT_AUTHORIZED", CtraderErrorCode.NOT_AUTHORIZED),
        ("CH_CTID_TRADER_ACCOUNT_NOT_FOUND", CtraderErrorCode.NOT_AUTHORIZED),
        ("CH_CLIENT_AUTH_FAILURE", CtraderErrorCode.CLIENT_AUTH_FAILED),
        ("REQUEST_FREQUENCY_EXCEEDED", CtraderErrorCode.RATE_LIMITED),
        ("BLOCKED_PAYLOAD_TYPE", CtraderErrorCode.RATE_LIMITED),
        ("SERVER_IS_UNDER_MAINTENANCE", CtraderErrorCode.CONNECTION_FAILED),
        ("SOMETHING_NEW", CtraderErrorCode.BAD_RESPONSE),
    ],
)
def test_server_error_mapping(server_code: str, expected: CtraderErrorCode) -> None:
    assert error_from_server(server_code, "text", None).code is expected


def test_server_error_text_is_masked() -> None:
    error = error_from_server("X", f"bad token {ACCESS_TOKEN}", None, secrets=(ACCESS_TOKEN,))
    assert ACCESS_TOKEN not in str(error)
    assert ACCESS_TOKEN not in repr(error)


def test_error_res_honours_retry_after_then_succeeds() -> None:
    calls: list[int] = []

    def handler(_frame: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append(1)
        if len(calls) == 1:
            return p.ERROR_RES, {"errorCode": "BLOCKED_PAYLOAD_TYPE", "retryAfter": 3}
        return p.TRADER_RES, {"ok": True}

    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    transport = FakeTransport({p.TRADER_REQ: handler})

    async def scenario() -> dict[str, Any]:
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=sleep)
        await connection.start()
        try:
            return await connection.request(p.TRADER_REQ, {}, p.TRADER_RES)
        finally:
            await connection.close()

    assert asyncio.run(scenario()) == {"ok": True}
    assert slept == [3.0]


def test_retry_after_too_long_is_not_waited_for() -> None:
    error = (p.ERROR_RES, {"errorCode": "BLOCKED_PAYLOAD_TYPE", "retryAfter": 3600})
    transport = FakeTransport({p.TRADER_REQ: error})
    with pytest.raises(CtraderError) as caught:
        _with_connection(transport, lambda c: c.request(p.TRADER_REQ, {}, p.TRADER_RES))
    assert _code(caught) is CtraderErrorCode.RATE_LIMITED
    assert caught.value.retry_after == 3600
    assert transport.types_sent().count(p.TRADER_REQ) == 1


def test_rate_limiter_enforces_the_window() -> None:
    clock = [0.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    limiter = RateLimiter(2, 1.0, clock=lambda: clock[0], sleep=sleep)

    async def scenario() -> None:
        for _ in range(3):
            await limiter.acquire()

    asyncio.run(scenario())
    assert slept == [1.0]


def test_connection_limits_match_the_documented_rates() -> None:
    assert p.MAX_REQUESTS_PER_S == 50
    assert p.MAX_HISTORICAL_REQUESTS_PER_S == 5


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (p.ACCOUNTS_TOKEN_INVALIDATED_EVENT, CtraderErrorCode.TOKEN_INVALID),
        (p.CLIENT_DISCONNECT_EVENT, CtraderErrorCode.CONNECTION_FAILED),
        (p.ACCOUNT_DISCONNECT_EVENT, CtraderErrorCode.ACCOUNT_DISCONNECTED),
    ],
)
def test_server_event_fails_the_pending_request(event: int, expected: CtraderErrorCode) -> None:
    transport = FakeTransport({p.TRADER_REQ: None})

    async def body(connection: CtraderConnection) -> None:
        pending = asyncio.create_task(connection.request(p.TRADER_REQ, {}, p.TRADER_RES))
        await asyncio.sleep(0.01)
        transport.push(event, {"ctidTraderAccountId": CTID})
        await pending

    with pytest.raises(CtraderError) as caught:
        _with_connection(transport, body)
    assert _code(caught) is expected


def test_dropped_socket_fails_the_pending_request() -> None:
    transport = FakeTransport({p.TRADER_REQ: None})

    async def body(connection: CtraderConnection) -> None:
        pending = asyncio.create_task(connection.request(p.TRADER_REQ, {}, p.TRADER_RES))
        await asyncio.sleep(0.01)
        transport.push_raw(OSError("socket closed"))
        await pending

    with pytest.raises(CtraderError) as caught:
        _with_connection(transport, body)
    assert _code(caught) is CtraderErrorCode.CONNECTION_FAILED


def test_broken_frame_is_skipped() -> None:
    transport = FakeTransport()

    async def body(connection: CtraderConnection) -> dict[str, Any]:
        transport.push_raw("not json")
        return await connection.request(p.APPLICATION_AUTH_REQ, {}, p.APPLICATION_AUTH_RES)

    assert _with_connection(transport, body) == {}


def test_read_balance_scales_and_adds_net_pnl() -> None:
    result = _with_connection(FakeTransport(), lambda c: read_balance(c, CREDS, CTID))
    assert result.balance == Decimal("1000.50")
    assert result.equity == Decimal("1012.84")
    assert result.equity_error is None


def test_read_balance_uses_each_message_money_digits() -> None:
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (
        p.POSITION_PNL_RES,
        {
            "ctidTraderAccountId": CTID,
            "moneyDigits": 8,
            "positionUnrealizedPnL": [{"positionId": 1, "netUnrealizedPnL": 150000000}],
        },
    )
    result = _with_connection(FakeTransport(handlers), lambda c: read_balance(c, CREDS, CTID))
    assert result.equity == Decimal("1002.00")


def test_no_positions_means_equity_equals_balance() -> None:
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (
        p.POSITION_PNL_RES,
        {"ctidTraderAccountId": CTID, "moneyDigits": 2},
    )
    result = _with_connection(FakeTransport(handlers), lambda c: read_balance(c, CREDS, CTID))
    assert result.equity == Decimal("1000.50")


def test_failed_pnl_read_gives_no_equity() -> None:
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (p.ERROR_RES, {"errorCode": "SOMETHING_NEW"})
    result = _with_connection(FakeTransport(handlers), lambda c: read_balance(c, CREDS, CTID))
    assert result.balance == Decimal("1000.50")
    assert result.equity is None
    assert result.equity_error == CtraderErrorCode.BAD_RESPONSE.value


def test_pnl_without_net_value_gives_no_equity() -> None:
    handlers = default_handlers()
    handlers[p.POSITION_PNL_REQ] = (
        p.POSITION_PNL_RES,
        {
            "ctidTraderAccountId": CTID,
            "moneyDigits": 2,
            "positionUnrealizedPnL": [{"positionId": 1}],
        },
    )
    result = _with_connection(FakeTransport(handlers), lambda c: read_balance(c, CREDS, CTID))
    assert result.equity is None


def test_missing_money_digits_never_assumes_a_scale() -> None:
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = (
        p.TRADER_RES,
        {"ctidTraderAccountId": CTID, "trader": {"ctidTraderAccountId": CTID, "balance": 100050}},
    )
    with pytest.raises(CtraderError) as caught:
        _with_connection(FakeTransport(handlers), lambda c: read_balance(c, CREDS, CTID))
    assert _code(caught) is CtraderErrorCode.BAD_RESPONSE


def test_answer_for_another_account_is_refused() -> None:
    handlers = default_handlers()
    handlers[p.TRADER_REQ] = (
        p.TRADER_RES,
        {"ctidTraderAccountId": CTID + 1, "trader": {"balance": 100050, "moneyDigits": 2}},
    )
    with pytest.raises(CtraderError) as caught:
        _with_connection(FakeTransport(handlers), lambda c: read_balance(c, CREDS, CTID))
    assert _code(caught) is CtraderErrorCode.BAD_RESPONSE


def test_fetch_account_list() -> None:
    transport = FakeTransport()
    grant = asyncio.run(fetch_account_list(CREDS, FakeConnector(transport), sleep=no_sleep))
    assert grant.view_only is True
    assert [(a.ctid, a.is_live, a.trader_login, a.broker) for a in grant.accounts] == [
        (CTID, False, TRADER_LOGIN, "Demo Broker")
    ]
    assert transport.types_sent()[:2] == [p.APPLICATION_AUTH_REQ, p.ACCOUNT_LIST_REQ]
    assert transport.closed


@pytest.mark.parametrize("scope", ["SCOPE_TRADE", 1, None, "", "scope_view"])
def test_any_scope_but_view_is_not_view_only(scope: object) -> None:
    handlers = default_handlers()
    handlers[p.ACCOUNT_LIST_REQ] = (p.ACCOUNT_LIST_RES, account_list_payload(scope))
    grant = asyncio.run(
        fetch_account_list(CREDS, FakeConnector(FakeTransport(handlers)), sleep=no_sleep)
    )
    assert grant.view_only is False


@pytest.mark.parametrize("scope", ["SCOPE_VIEW", 0])
def test_view_scope_by_name_or_number(scope: object) -> None:
    handlers = default_handlers()
    handlers[p.ACCOUNT_LIST_REQ] = (p.ACCOUNT_LIST_RES, account_list_payload(scope))
    grant = asyncio.run(
        fetch_account_list(CREDS, FakeConnector(FakeTransport(handlers)), sleep=no_sleep)
    )
    assert grant.view_only is True


def test_read_balances_uses_one_connection_per_environment() -> None:
    demo, live = FakeTransport(), FakeTransport()
    for transport, ctid in ((demo, 1), (live, 2)):
        transport.handlers = _handlers_for(ctid)

    async def connector(url: str) -> FakeTransport:
        return live if "live" in url else demo

    results = asyncio.run(read_balances(CREDS, [(1, False), (2, True)], connector, sleep=no_sleep))
    for ctid in (1, 2):
        read = results[ctid]
        assert not isinstance(read, CtraderError)
        assert read.balance == Decimal("1000.50")
    assert demo.types_sent().count(p.TRADER_REQ) == 2  # before and after the P&L
    assert live.types_sent().count(p.TRADER_REQ) == 2
    assert demo.closed
    assert live.closed


def test_read_balances_isolates_an_environment_failure() -> None:
    demo = FakeTransport(_handlers_for(1))

    async def connector(url: str) -> FakeTransport:
        if "live" in url:
            raise OSError("down")
        return demo

    results = asyncio.run(read_balances(CREDS, [(1, False), (2, True)], connector, sleep=no_sleep))
    assert not isinstance(results[1], CtraderError)
    failed = results[2]
    assert isinstance(failed, CtraderError)
    assert failed.code is CtraderErrorCode.CONNECTION_FAILED


def test_account_disconnect_is_retried_with_a_new_account_auth() -> None:
    attempts: list[int] = []
    handlers = default_handlers()
    good = handlers[p.TRADER_REQ]

    def trader(frame: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
        attempts.append(1)
        if len(attempts) == 1:
            transport.push(p.ACCOUNT_DISCONNECT_EVENT, {"ctidTraderAccountId": CTID})
            return None
        assert isinstance(good, tuple)
        return good

    handlers[p.TRADER_REQ] = trader
    transport = FakeTransport(handlers)

    async def connector(_url: str) -> FakeTransport:
        return transport

    results = asyncio.run(read_balances(CREDS, [(CTID, False)], connector, sleep=no_sleep))
    read = results[CTID]
    assert not isinstance(read, CtraderError)
    assert read.balance == Decimal("1000.50")
    assert transport.types_sent().count(p.ACCOUNT_AUTH_REQ) == 2


def test_tokens_are_absent_from_credentials_repr() -> None:
    assert ACCESS_TOKEN not in repr(CREDS)
    assert CLIENT_SECRET not in repr(CREDS)


def test_auth_frames_carry_credentials_only_on_the_wire() -> None:
    transport = FakeTransport()
    _with_connection(transport, lambda c: read_balance(c, CREDS, CTID))
    wire = json.dumps(transport.sent)
    assert ACCESS_TOKEN in wire  # account auth needs it; every other surface is tested clean


def _handlers_for(ctid: int) -> dict[int, Any]:
    handlers = default_handlers()
    handlers[p.ACCOUNT_AUTH_REQ] = (p.ACCOUNT_AUTH_RES, {"ctidTraderAccountId": ctid})
    handlers[p.TRADER_REQ] = (
        p.TRADER_RES,
        {"ctidTraderAccountId": ctid, "trader": {"balance": 100050, "moneyDigits": 2}},
    )
    handlers[p.POSITION_PNL_REQ] = (
        p.POSITION_PNL_RES,
        {"ctidTraderAccountId": ctid, "moneyDigits": 2},
    )
    return handlers

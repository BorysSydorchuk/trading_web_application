"""One asyncio WebSocket connection to cTrader: send guard, heartbeat, limits, events.

Live and demo need separate connections. `_send` is the only function that writes to the
socket, and it checks `guard.assert_allowed` first.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Final, Protocol

from websockets.asyncio.client import ClientConnection, connect

from app.ctrader import guard
from app.ctrader import protocol as p
from app.ctrader.errors import CtraderError, CtraderErrorCode, error_from_server
from app.ctrader.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S: Final = 10.0
REQUEST_TIMEOUT_S: Final = 15.0
CLOSE_TIMEOUT_S: Final = 3.0
CONNECT_ATTEMPTS: Final = 3
BACKOFF_BASE_S: Final = 1.0
BACKOFF_CAP_S: Final = 30.0
RATE_LIMIT_RETRIES: Final = 1
MAX_RETRY_WAIT_S: Final = 30.0
MAX_FRAME_BYTES: Final = 2**20

Sleep = Callable[[float], Awaitable[None]]


class Transport(Protocol):
    async def send(self, data: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[Transport]]


class _WebSocketTransport:
    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket

    async def send(self, data: str) -> None:
        await self._socket.send(data)

    async def recv(self) -> str | bytes:
        return await self._socket.recv()

    async def close(self) -> None:
        await self._socket.close()


async def open_websocket(url: str) -> Transport:
    """The real connector. Pings are off: cTrader uses its own heartbeat message."""
    socket = await connect(
        url,
        open_timeout=CONNECT_TIMEOUT_S,
        close_timeout=CLOSE_TIMEOUT_S,
        ping_interval=None,
        max_size=MAX_FRAME_BYTES,
    )
    return _WebSocketTransport(socket)


def backoff_delays(
    attempts: int, *, base: float = BACKOFF_BASE_S, cap: float = BACKOFF_CAP_S
) -> list[float]:
    """Waits between ``attempts`` tries: exponential, capped."""
    return [min(base * 2**index, cap) for index in range(attempts - 1)]


def _retry_after(payload: dict[str, Any]) -> float | None:
    value = payload.get("retryAfter")
    return float(value) if type(value) is int and value >= 0 else None


class CtraderConnection:
    def __init__(
        self,
        url: str,
        connector: Connector = open_websocket,
        *,
        sleep: Sleep = asyncio.sleep,
        secrets: Iterable[str] = (),
        request_timeout_s: float = REQUEST_TIMEOUT_S,
        heartbeat_s: float = p.HEARTBEAT_INTERVAL_S,
    ) -> None:
        self._url = url
        self._connector = connector
        self._sleep = sleep
        self._secrets = tuple(secrets)
        self._request_timeout_s = request_timeout_s
        self._heartbeat_s = heartbeat_s
        self._limiter = RateLimiter(p.MAX_REQUESTS_PER_S, 1.0)
        self._historical = RateLimiter(p.MAX_HISTORICAL_REQUESTS_PER_S, 1.0)
        self._transport: Transport | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._pending: dict[str, asyncio.Future[p.Frame]] = {}
        self._broken = False

    async def open(self) -> None:
        """Connect with exponential backoff; raises ``connection_failed`` when out of tries."""
        delays = backoff_delays(CONNECT_ATTEMPTS)
        for attempt in range(CONNECT_ATTEMPTS):
            try:
                self._transport = await asyncio.wait_for(
                    self._connector(self._url), CONNECT_TIMEOUT_S
                )
                break
            except Exception as exc:
                logger.warning(
                    "cTrader connect attempt %s/%s failed: %s",
                    attempt + 1,
                    CONNECT_ATTEMPTS,
                    type(exc).__name__,
                )
                if attempt == CONNECT_ATTEMPTS - 1:
                    raise CtraderError(
                        CtraderErrorCode.CONNECTION_FAILED, "could not connect to cTrader"
                    ) from None
                await self._sleep(delays[attempt])
        self._broken = False
        self._tasks = [
            asyncio.create_task(self._read_loop()),
            asyncio.create_task(self._heartbeat_loop()),
        ]

    async def close(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._fail_pending(CtraderError(CtraderErrorCode.CONNECTION_FAILED, "connection closed"))
        transport, self._transport = self._transport, None
        if transport is None:
            return
        try:
            await asyncio.wait_for(transport.close(), CLOSE_TIMEOUT_S)
        except Exception as exc:
            logger.debug("cTrader close failed: %s", type(exc).__name__)

    async def reopen(self) -> None:
        await self.close()
        await self.open()

    async def request(
        self,
        payload_type: int,
        payload: dict[str, Any],
        expect: int,
        *,
        historical: bool = False,
    ) -> dict[str, Any]:
        """Send and wait for the answer; honours ``retryAfter`` once when it is short."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return await self._request_once(payload_type, payload, expect, historical)
            except CtraderError as exc:
                wait = exc.retry_after
                if (
                    exc.code is not CtraderErrorCode.RATE_LIMITED
                    or wait is None
                    or attempt == RATE_LIMIT_RETRIES
                    or wait > MAX_RETRY_WAIT_S
                ):
                    raise
                logger.warning("cTrader rate limit: waiting %s s", wait)
                await self._sleep(wait)
        raise CtraderError(CtraderErrorCode.RATE_LIMITED, "rate limited")  # pragma: no cover

    async def _request_once(
        self, payload_type: int, payload: dict[str, Any], expect: int, historical: bool
    ) -> dict[str, Any]:
        guard.assert_allowed(payload_type)  # before waiting on a limiter
        if historical:
            await self._historical.acquire()
        await self._limiter.acquire()
        msg_id = uuid.uuid4().hex
        future: asyncio.Future[p.Frame] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            await self._send(msg_id, payload_type, payload)
            frame = await asyncio.wait_for(future, self._request_timeout_s)
        except TimeoutError:
            raise CtraderError(
                CtraderErrorCode.TIMEOUT, f"no answer to message {payload_type}"
            ) from None
        finally:
            self._pending.pop(msg_id, None)
        if frame.payload_type != expect:
            raise CtraderError(
                CtraderErrorCode.BAD_RESPONSE,
                f"message {frame.payload_type} instead of {expect}",
            )
        return frame.payload

    async def _send(self, msg_id: str, payload_type: int, payload: dict[str, Any]) -> None:
        """The single write to the socket. The allowlist check comes first."""
        guard.assert_allowed(payload_type)
        if self._transport is None or self._broken:
            raise CtraderError(CtraderErrorCode.CONNECTION_FAILED, "not connected")
        try:
            await self._transport.send(p.encode_frame(msg_id, payload_type, payload))
        except Exception as exc:
            self._broken = True
            raise CtraderError(
                CtraderErrorCode.CONNECTION_FAILED, f"send failed: {type(exc).__name__}"
            ) from None

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_s)
            try:
                await self._send(uuid.uuid4().hex, p.HEARTBEAT, dict(p.HEARTBEAT_PAYLOAD))
            except CtraderError as exc:
                self._fail_pending(exc)
                return

    async def _read_loop(self) -> None:
        transport = self._transport
        if transport is None:  # pragma: no cover - started right after connecting
            return
        while True:
            try:
                raw = await transport.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._broken = True
                self._fail_pending(
                    CtraderError(
                        CtraderErrorCode.CONNECTION_FAILED,
                        f"connection lost: {type(exc).__name__}",
                    )
                )
                return
            try:
                frame = p.decode_frame(raw)
            except ValueError:
                logger.warning("cTrader sent a malformed frame; skipped")
                continue
            self._dispatch(frame)

    def _dispatch(self, frame: p.Frame) -> None:
        if frame.payload_type in (p.ERROR_RES, p.COMMON_ERROR_RES):
            self._on_error(frame)
        elif frame.payload_type == p.ACCOUNTS_TOKEN_INVALIDATED_EVENT:
            self._fail_pending(CtraderError(CtraderErrorCode.TOKEN_INVALID, "token invalidated"))
        elif frame.payload_type == p.CLIENT_DISCONNECT_EVENT:
            self._broken = True
            self._fail_pending(
                CtraderError(CtraderErrorCode.CONNECTION_FAILED, "server closed the session")
            )
        elif frame.payload_type == p.ACCOUNT_DISCONNECT_EVENT:
            self._fail_pending(
                CtraderError(CtraderErrorCode.ACCOUNT_DISCONNECTED, "account session dropped")
            )
        elif frame.client_msg_id is not None:
            future = self._pending.get(frame.client_msg_id)
            if future is not None and not future.done():
                future.set_result(frame)

    def _on_error(self, frame: p.Frame) -> None:
        error = error_from_server(
            str(frame.payload.get("errorCode", "UNKNOWN")),
            frame.payload.get("description"),
            _retry_after(frame.payload),
            secrets=self._secrets,
        )
        logger.warning("cTrader error: %s", error.message)
        future = self._pending.get(frame.client_msg_id) if frame.client_msg_id else None
        if future is None:
            self._fail_pending(error)
        elif not future.done():
            future.set_exception(error)

    def _fail_pending(self, error: CtraderError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

"""`Mt5Source` over the official ``MetaTrader5`` package (Windows only, read-only).

- The package is imported lazily, so this module imports fine on Linux/CI and in tests,
  which inject a fake module object instead.
- Only the read functions listed in `ALLOWED_FUNCTIONS` are ever touched; the guard tests
  check this and grep ``app`` for trading calls.
- Every call returning None is turned into a typed `Mt5Error` from ``last_error()``.
- Every call runs with a wall-clock timeout in a daemon thread; ``last_error()`` is read in
  that same thread (MT5 may keep it per thread). After a timeout the source is broken:
  calls fail fast, and nothing (not even ``connect``/``shutdown``) enters the module again
  while the timed-out thread is still inside it.
- Reads are retried once on transient IPC errors (safe: they don't change anything).
- The password is passed to ``initialize`` only, never logged, and masked in every message.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any, Protocol, cast

from pydantic import SecretStr

from app.mt5.errors import (
    EMPTY_CODES,
    RES_E_FAIL,
    TRANSIENT_CODES,
    Mt5Error,
    Mt5ErrorCode,
    error_from_last_error,
    mask_secrets,
    split_last_error,
)
from app.mt5.source import (
    DEFAULT_CONNECT_TIMEOUT_S,
    match_prefixes,
    require_password,
    resolve_terminal,
    verify_account,
)
from app.mt5.types import (
    DIRECTIONS,
    Direction,
    RawAccountInfo,
    RawDeal,
    RawOrder,
    RawPosition,
    RawSymbolSpec,
    to_decimal,
)

logger = logging.getLogger(__name__)

DEFAULT_CALL_TIMEOUT_S = 30.0
SHUTDOWN_TIMEOUT_S = 5.0
RETRY_DELAY_S = 0.5
# Extra wall-clock time on top of initialize's own timeout (terminal start-up).
CONNECT_GRACE_S = 15.0

ALLOWED_FUNCTIONS = frozenset(
    {
        "initialize",
        "shutdown",
        "last_error",
        "account_info",
        "symbol_info",
        "symbol_info_tick",
        "symbol_select",  # adds a symbol to Market Watch so it gets ticks; not trading
        "symbols_get",
        "history_deals_get",
        "history_orders_get",
        "positions_get",
        # Hypothetical required margin (PRD 6.8): only calculates, never places/checks orders.
        "order_calc_margin",
    }
)
# Module constants read besides the functions above (arguments of order_calc_margin).
ALLOWED_CONSTANTS = frozenset({"ORDER_TYPE_BUY", "ORDER_TYPE_SELL"})


class Mt5Module(Protocol):
    """The subset of the ``MetaTrader5`` module we use (all read-only)."""

    def initialize(self, path: str, **kwargs: Any) -> bool: ...
    def shutdown(self) -> Any: ...
    def last_error(self) -> Any: ...
    def account_info(self) -> Any: ...
    def symbol_info(self, symbol: str) -> Any: ...
    def symbol_info_tick(self, symbol: str) -> Any: ...
    def symbol_select(self, symbol: str, enable: bool) -> Any: ...
    def symbols_get(self, *args: Any, **kwargs: Any) -> Any: ...
    def history_deals_get(self, *args: Any, **kwargs: Any) -> Any: ...
    def history_orders_get(self, *args: Any, **kwargs: Any) -> Any: ...
    def positions_get(self, *args: Any, **kwargs: Any) -> Any: ...
    def order_calc_margin(self, action: int, symbol: str, volume: float, price: float) -> Any: ...

    @property
    def ORDER_TYPE_BUY(self) -> int: ...  # noqa: N802 - MetaTrader5 module constant
    @property
    def ORDER_TYPE_SELL(self) -> int: ...  # noqa: N802 - MetaTrader5 module constant


def load_module() -> Mt5Module:
    try:
        module = importlib.import_module("MetaTrader5")
    except ImportError:
        raise Mt5Error(
            Mt5ErrorCode.MT5_ERROR,
            "MetaTrader5 Python package is not installed (it exists for Windows only)",
        ) from None
    return cast(Mt5Module, module)


def _int(obj: object, name: str, default: int = 0) -> int:
    value = getattr(obj, name, default)
    return default if value is None else int(value)


def _dec(obj: object, name: str) -> Any:
    return to_decimal(getattr(obj, name, 0) or 0)


def _opt_dec(obj: object, name: str) -> Decimal | None:
    value = getattr(obj, name, None)
    return None if value is None else to_decimal(value)


def _str(obj: object, name: str) -> str:
    value = getattr(obj, name, "")
    return "" if value is None else str(value)


def account_from_mt5(obj: object) -> RawAccountInfo:
    return RawAccountInfo(
        login=_int(obj, "login"),
        server=_str(obj, "server"),
        balance=_dec(obj, "balance"),
        equity=_dec(obj, "equity"),
        currency=_str(obj, "currency"),
    )


def spec_from_mt5(obj: object) -> RawSymbolSpec:
    return RawSymbolSpec(
        name=_str(obj, "name"),
        digits=_int(obj, "digits"),
        contract_size=_dec(obj, "trade_contract_size"),
        tick_size=_dec(obj, "trade_tick_size"),
        tick_value=_dec(obj, "trade_tick_value"),
        volume_min=_dec(obj, "volume_min"),
        volume_step=_dec(obj, "volume_step"),
        volume_max=_dec(obj, "volume_max"),
        currency_profit=_str(obj, "currency_profit"),
        currency_margin=_str(obj, "currency_margin"),
        point=_opt_dec(obj, "point"),
        tick_value_loss=_opt_dec(obj, "trade_tick_value_loss"),
    )


def deal_from_mt5(obj: object) -> RawDeal:
    return RawDeal(
        ticket=_int(obj, "ticket"),
        order=_int(obj, "order"),
        position_id=_int(obj, "position_id"),
        time=_int(obj, "time"),
        time_msc=_int(obj, "time_msc"),
        type=_int(obj, "type"),
        entry=_int(obj, "entry"),
        reason=_int(obj, "reason"),
        magic=_int(obj, "magic"),
        volume=_dec(obj, "volume"),
        price=_dec(obj, "price"),
        profit=_dec(obj, "profit"),
        commission=_dec(obj, "commission"),
        swap=_dec(obj, "swap"),
        fee=_dec(obj, "fee"),
        symbol=_str(obj, "symbol"),
        # DEAL_SL/DEAL_TP only exist in newer terminal builds.
        sl=_opt_dec(obj, "sl"),
        tp=_opt_dec(obj, "tp"),
    )


def order_from_mt5(obj: object) -> RawOrder:
    return RawOrder(
        ticket=_int(obj, "ticket"),
        position_id=_int(obj, "position_id"),
        time_setup=_int(obj, "time_setup"),
        time_setup_msc=_int(obj, "time_setup_msc"),
        type=_int(obj, "type"),
        state=_int(obj, "state"),
        volume_initial=_dec(obj, "volume_initial"),
        price_open=_dec(obj, "price_open"),
        sl=_dec(obj, "sl"),
        tp=_dec(obj, "tp"),
        symbol=_str(obj, "symbol"),
    )


def position_from_mt5(obj: object) -> RawPosition:
    return RawPosition(
        ticket=_int(obj, "ticket"),
        identifier=_int(obj, "identifier"),
        time=_int(obj, "time"),
        time_msc=_int(obj, "time_msc"),
        type=_int(obj, "type"),
        volume=_dec(obj, "volume"),
        price_open=_dec(obj, "price_open"),
        sl=_dec(obj, "sl"),
        tp=_dec(obj, "tp"),
        price_current=_dec(obj, "price_current"),
        profit=_dec(obj, "profit"),
        swap=_dec(obj, "swap"),
        symbol=_str(obj, "symbol"),
    )


class RealMt5Source:
    """One terminal at a time; the worker connects, reads and shuts down per account."""

    def __init__(
        self,
        module: Mt5Module | None = None,
        *,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
        retries: int = 1,
        retry_delay_s: float = RETRY_DELAY_S,
    ) -> None:
        self._module = module
        self._call_timeout_s = call_timeout_s
        self._retries = retries
        self._retry_delay_s = retry_delay_s
        self._connected = False
        self._broken: Mt5Error | None = None
        # Thread of the last module call; after a timeout it may still be inside the module.
        self._thread: threading.Thread | None = None

    # -- plumbing ---------------------------------------------------------------

    def _mt5(self) -> Mt5Module:
        if self._module is None:
            self._module = load_module()
        return self._module

    def _ensure_idle(self) -> None:
        """Never enter the module while a timed-out call is still running inside it."""
        if self._thread is not None and self._thread.is_alive():
            raise Mt5Error(
                Mt5ErrorCode.TIMEOUT,
                "previous MT5 call still running; restart the terminal/worker",
            )

    def _run[T](self, what: str, fn: Callable[[], T], timeout_s: float) -> T:
        """Run ``fn`` in a tracked daemon thread with a deadline."""
        self._ensure_idle()
        result: list[T] = []
        error: list[BaseException] = []
        done = threading.Event()

        def target() -> None:
            try:
                result.append(fn())
            except BaseException as exc:  # re-raised in the caller's thread
                error.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=target, name=f"mt5-{what}", daemon=True)
        self._thread = thread
        thread.start()
        if not done.wait(timeout_s):
            raise Mt5Error(
                Mt5ErrorCode.TIMEOUT, f"MT5 {what} did not answer within {timeout_s:g} s"
            )
        if error:
            raise error[0]
        return result[0]

    def _call(
        self,
        what: str,
        fn: Callable[[], Any],
        timeout_s: float | None = None,
        secrets: Iterable[str] = (),
    ) -> tuple[Any, tuple[int, str] | None]:
        """Call ``fn``; if it returns None/False, read ``last_error()`` in the SAME thread.

        MT5 may keep the last error per thread, so it must be read where the call failed.
        Returns ``(result, last_error)``; ``last_error`` is None when the call succeeded.
        """
        if self._broken is not None:
            raise Mt5Error(
                Mt5ErrorCode.TIMEOUT, f"MT5 connection is unusable after: {self._broken.message}"
            )
        mt5 = self._mt5()

        def call_and_error() -> tuple[Any, tuple[int, str] | None]:
            value = fn()
            if value is None or value is False:
                return value, split_last_error(mt5.last_error())
            return value, None

        try:
            return self._run(what, call_and_error, timeout_s or self._call_timeout_s)
        except Mt5Error as exc:
            if exc.code is Mt5ErrorCode.TIMEOUT:
                self._broken = exc
            raise
        except Exception as exc:  # the C extension raising: keep a short, masked message
            raise Mt5Error(
                Mt5ErrorCode.MT5_ERROR,
                f"{what} raised {type(exc).__name__}: {exc}",
                secrets=secrets,
            ) from None

    def _require_connected(self) -> None:
        if not self._connected:
            raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "not connected to an MT5 terminal")

    def _read(self, what: str, fn: Callable[[], Any], *, empty_ok: bool) -> Any:
        """Call ``fn``; None -> None when MT5 says "nothing there" and ``empty_ok``, else error.

        Transient IPC failures are retried ``retries`` times (reads are idempotent).
        """
        self._require_connected()
        attempt = 0
        while True:
            result, last_error = self._call(what, fn)
            if result is not None:
                return result
            code, message = last_error if last_error is not None else (RES_E_FAIL, "no result")
            if empty_ok and code in EMPTY_CODES:
                return None
            if code in TRANSIENT_CODES and attempt < self._retries:
                attempt += 1
                logger.warning("MT5 %s failed (%s %s), retrying", what, code, message)
                time.sleep(self._retry_delay_s)
                continue
            raise error_from_last_error((code, message), during=what)

    # -- Mt5Source --------------------------------------------------------------

    def connect(
        self,
        terminal_path: str,
        login: int,
        password: SecretStr | None,
        server: str,
        timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    ) -> RawAccountInfo:
        secret = require_password(login, password)
        exe = resolve_terminal(terminal_path)
        mt5 = self._mt5()
        if self._connected:
            self.shutdown()
        # A timed-out call still inside the module: refuse, keep the broken state.
        self._ensure_idle()
        self._broken = None
        logger.info("MT5 connect: %s login=%s server=%s", exe, login, server)

        def init() -> bool:
            return bool(
                mt5.initialize(
                    str(exe),
                    login=login,
                    password=secret,
                    server=server,
                    timeout=int(timeout_s * 1000),
                    portable=True,
                )
            )

        try:
            ok, last_error = self._call(
                "initialize", init, timeout_s + CONNECT_GRACE_S, secrets=(secret,)
            )
            if not ok:
                code_msg = last_error if last_error is not None else (RES_E_FAIL, "failed")
                raise error_from_last_error(code_msg, during="initialize", secrets=(secret,))
            self._connected = True
            info = self.account_info()
            verify_account(info, login, server)
        except Mt5Error as exc:
            self.shutdown()
            # Message is already masked; re-mask defensively and drop the original chain.
            raise Mt5Error(
                exc.code, mask_secrets(exc.message, (secret,)), mt5_code=exc.mt5_code
            ) from None
        logger.info("MT5 connected: login=%s server=%s", info.login, info.server)
        return info

    def shutdown(self) -> None:
        if self._module is None:
            return
        mt5 = self._module
        try:
            self._run("shutdown", mt5.shutdown, SHUTDOWN_TIMEOUT_S)
        except Exception as exc:  # shutdown must never raise
            logger.warning("MT5 shutdown skipped/failed: %s", exc)
        self._connected = False

    def account_info(self) -> RawAccountInfo:
        obj = self._read("account_info", self._mt5().account_info, empty_ok=False)
        return account_from_mt5(obj)

    def server_tick_epoch(self, symbol: str) -> int | None:
        mt5 = self._mt5()
        tick = self._read("symbol_info_tick", lambda: mt5.symbol_info_tick(symbol), empty_ok=True)
        if tick is None:
            # Not in Market Watch: select it (display only) and ask once more.
            self._read("symbol_select", lambda: mt5.symbol_select(symbol, True), empty_ok=True)
            tick = self._read(
                "symbol_info_tick", lambda: mt5.symbol_info_tick(symbol), empty_ok=True
            )
        if tick is None:
            return None
        epoch = _int(tick, "time")
        return epoch or None

    def symbol_spec(self, symbol: str) -> RawSymbolSpec | None:
        mt5 = self._mt5()
        obj = self._read("symbol_info", lambda: mt5.symbol_info(symbol), empty_ok=True)
        return None if obj is None else spec_from_mt5(obj)

    def symbols_matching(self, prefixes: Iterable[str]) -> list[RawSymbolSpec]:
        objs = self._read("symbols_get", self._mt5().symbols_get, empty_ok=True) or ()
        by_name = {_str(o, "name"): o for o in objs}
        return [spec_from_mt5(by_name[n]) for n in match_prefixes(by_name, prefixes)]

    def deals(self, from_server_epoch: int, to_server_epoch: int) -> list[RawDeal]:
        mt5 = self._mt5()
        objs = self._read(
            "history_deals_get",
            lambda: mt5.history_deals_get(from_server_epoch, to_server_epoch),
            empty_ok=True,
        )
        deals = [deal_from_mt5(o) for o in objs or ()]
        deals.sort(key=lambda d: (d.time, d.ticket))
        return deals

    def deals_for_position(self, position_id: int) -> list[RawDeal]:
        mt5 = self._mt5()
        objs = self._read(
            "history_deals_get", lambda: mt5.history_deals_get(position=position_id), empty_ok=True
        )
        deals = [deal_from_mt5(o) for o in objs or ()]
        deals.sort(key=lambda d: (d.time, d.ticket))
        return deals

    def opening_order(self, order_ticket: int) -> RawOrder | None:
        mt5 = self._mt5()
        objs = self._read(
            "history_orders_get", lambda: mt5.history_orders_get(ticket=order_ticket), empty_ok=True
        )
        return order_from_mt5(objs[0]) if objs else None

    def open_positions(self) -> list[RawPosition]:
        objs = self._read("positions_get", self._mt5().positions_get, empty_ok=True)
        return [position_from_mt5(o) for o in objs or ()]

    def calc_margin(
        self, direction: Direction, symbol: str, volume: Decimal, price: Decimal
    ) -> Decimal:
        """``order_calc_margin``: required margin in account currency (read-only)."""
        if direction not in DIRECTIONS:
            raise ValueError(f"direction must be 'buy' or 'sell', got {direction!r}")
        mt5 = self._mt5()  # _read checks the connection before the module is called
        action = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
        result = self._read(
            "order_calc_margin",
            lambda: mt5.order_calc_margin(action, symbol, float(volume), float(price)),
            empty_ok=False,
        )
        return margin_from_mt5(result)


def margin_from_mt5(value: object) -> Decimal:
    """A finite, non-negative margin, else `Mt5Error(mt5_error)` (never a silent zero)."""
    try:
        margin = to_decimal(value)
    except ValueError as exc:
        raise Mt5Error(Mt5ErrorCode.MT5_ERROR, f"order_calc_margin returned {exc}") from None
    if margin < 0:
        raise Mt5Error(Mt5ErrorCode.MT5_ERROR, f"order_calc_margin returned {margin} (< 0)")
    return margin

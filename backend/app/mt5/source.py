"""The read-only MT5 data source interface (PRD 6.2) and checks shared by implementations.

An `Mt5Source` talks to ONE terminal at a time (the MetaTrader5 package is process-global):
``connect`` -> reads -> ``shutdown``. All methods return raw records (`app.mt5.types`):
times are server wall-clock epochs, converted to UTC only by `app.mt5.convert`.

The interface is read-only by design: there is no method that could place, modify or close
anything (``calc_margin`` only calculates a hypothetical margin), and
`tests/mt5/test_guard.py` fails if trading calls appear anywhere in ``app``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from pydantic import SecretStr

from app.config import mt5_password_key
from app.domain.terminal_path import PROGRAM_FILES_MESSAGE, TERMINAL_EXE, is_in_program_files
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.types import (
    Direction,
    RawAccountInfo,
    RawDeal,
    RawOrder,
    RawPosition,
    RawSymbolSpec,
)

DEFAULT_CONNECT_TIMEOUT_S = 60.0


class Mt5Source(Protocol):
    def connect(
        self,
        terminal_path: str,
        login: int,
        password: SecretStr | None,
        server: str,
        timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    ) -> RawAccountInfo:
        """Start/attach the terminal, log in, verify the account. Raises `Mt5Error`."""
        ...

    def shutdown(self) -> None:
        """Disconnect; never raises."""
        ...

    def account_info(self) -> RawAccountInfo: ...

    def server_tick_epoch(self, symbol: str) -> int | None:
        """``symbol_info_tick(symbol).time`` (server wall epoch) or None if no tick."""
        ...

    def symbol_spec(self, symbol: str) -> RawSymbolSpec | None:
        """Exact symbol name; None if the broker has no such symbol."""
        ...

    def symbols_matching(self, prefixes: Iterable[str]) -> list[RawSymbolSpec]:
        """All symbols whose name starts with one of ``prefixes`` (broker suffixes)."""
        ...

    def deals(self, from_server_epoch: int, to_server_epoch: int) -> list[RawDeal]:
        """All deals with ``from <= time <= to`` (server epochs), sorted by (time, ticket)."""
        ...

    def deals_for_position(self, position_id: int) -> list[RawDeal]:
        """Every deal of one position, regardless of time."""
        ...

    def opening_order(self, order_ticket: int) -> RawOrder | None:
        """A history order by ticket (the opening order holds the initial SL/TP)."""
        ...

    def open_positions(self) -> list[RawPosition]: ...

    def calc_margin(
        self, direction: Direction, symbol: str, volume: Decimal, price: Decimal
    ) -> Decimal:
        """Required margin (account currency) to open ``volume`` lots at ``price``.

        Only calculates (MT5 ``order_calc_margin``); never places or checks an order.
        ``ValueError`` for an unknown direction, `Mt5Error` otherwise.
        """
        ...


def require_password(login: int, password: SecretStr | None) -> str:
    """The plain password for ``initialize``, or `Mt5Error(password_missing)`."""
    value = password.get_secret_value() if password is not None else ""
    if not value.strip():
        raise Mt5Error(
            Mt5ErrorCode.PASSWORD_MISSING,
            f"{mt5_password_key(login)} is not set in .env",
        )
    return value


def resolve_terminal(terminal_path: str) -> Path:
    """Accept the terminal64.exe path or its folder; `Mt5Error(terminal_not_found)` if absent.

    A path under Program Files is refused before any file access (accounts saved before the
    API check existed): `Mt5Error(terminal_in_program_files)`.
    """
    if not terminal_path.strip():
        raise Mt5Error(Mt5ErrorCode.TERMINAL_NOT_FOUND, "terminal path is not set for the account")
    if is_in_program_files(terminal_path):
        raise Mt5Error(Mt5ErrorCode.TERMINAL_IN_PROGRAM_FILES, PROGRAM_FILES_MESSAGE)
    path = Path(terminal_path.strip().strip('"'))
    if path.is_dir():
        path = path / TERMINAL_EXE
    if not path.is_file():
        raise Mt5Error(Mt5ErrorCode.TERMINAL_NOT_FOUND, f"terminal not found: {path}")
    return path


def verify_account(info: RawAccountInfo, login: int, server: str) -> None:
    """The terminal must be logged into exactly the requested account."""
    if info.login != login or info.server.strip().casefold() != server.strip().casefold():
        raise Mt5Error(
            Mt5ErrorCode.LOGIN_FAILED,
            f"terminal is logged into {info.login}@{info.server}, expected {login}@{server}",
        )


def match_prefixes(names: Iterable[str], prefixes: Iterable[str]) -> list[str]:
    """Names starting with any prefix (case-insensitive), in input order."""
    wanted = tuple(p.casefold() for p in prefixes if p)
    return [n for n in names if wanted and n.casefold().startswith(wanted)]


@contextmanager
def connected(
    source: Mt5Source,
    terminal_path: str,
    login: int,
    password: SecretStr | None,
    server: str,
    timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
) -> Iterator[RawAccountInfo]:
    """``with connected(...) as info:`` connect, yield verified account info, always shut down."""
    try:
        yield source.connect(terminal_path, login, password, server, timeout_s)
    finally:
        source.shutdown()

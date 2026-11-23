"""cTrader money values: integers scaled by ``10^moneyDigits``, exact Decimal, never float."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Final

from app.ctrader.errors import CtraderError, CtraderErrorCode

MAX_MONEY_DIGITS: Final = 18
_CENTS: Final = Decimal("0.01")
# accounts.balance / equity are NUMERIC(18, 2).
_STORED_LIMIT: Final = Decimal(10) ** 16
_WIDE: Final = Context(prec=80)


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


def parse_int(value: object, field: str) -> int:
    """An exact integer from JSON (a number, or digits: int64 may arrive as a string)."""
    if type(value) is int:
        return value
    if isinstance(value, str):
        digits = value[1:] if value.startswith("-") else value
        if digits.isascii() and digits.isdigit():
            return int(value)
    raise _bad(f"{field} is not an integer")


def scale_money(raw: int, digits: int) -> Decimal:
    """``raw / 10^digits`` built from the digit tuple: no context rounding can apply."""
    if not 0 <= digits <= MAX_MONEY_DIGITS:
        raise _bad(f"moneyDigits out of range: {digits}")
    sign, numerals, _exponent = Decimal(raw).as_tuple()
    return Decimal((sign, numerals, -digits))


def equity_from(balance: Decimal, net_pnl: Iterable[Decimal]) -> Decimal:
    """Balance + the positions' net unrealized P&L, without context rounding.

    The cTrader docs do not state this formula. ``netUnrealizedPnL`` does NOT include the
    potential closing commission, so this equity can be slightly above the platform's value
    while a position with a closing commission is open.
    """
    with localcontext(_WIDE):
        return sum(net_pnl, balance)


def to_stored(value: Decimal) -> Decimal:
    """Rounded half up to the cents of NUMERIC(18, 2); a value it cannot hold is refused."""
    with localcontext(_WIDE):
        stored = value.quantize(_CENTS, rounding=ROUND_HALF_UP)
    if abs(stored) >= _STORED_LIMIT:
        raise _bad("money value too large to store")
    return stored

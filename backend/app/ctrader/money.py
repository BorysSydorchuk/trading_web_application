"""cTrader money values: integers scaled by ``10^moneyDigits``, exact Decimal, never float."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Final

from app.ctrader.errors import CtraderError, CtraderErrorCode

MAX_MONEY_DIGITS: Final = 18
# The protocol's widest integer is uint64 (20 digits).
_MAX_INT_DIGITS: Final = 20
_INT_LIMIT: Final = 2**64
_CENTS: Final = Decimal("0.01")
# accounts.balance / equity are NUMERIC(18, 2).
_STORED_LIMIT: Final = Decimal(10) ** 16
_WIDE: Final = Context(prec=80)


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


def parse_int(value: object, field: str) -> int:
    """An exact integer from JSON (a number, or digits: int64 may arrive as a string)."""
    parsed: int | None = value if type(value) is int else None
    if isinstance(value, str):
        digits = value[1:] if value.startswith("-") else value
        if len(digits) <= _MAX_INT_DIGITS and digits.isascii() and digits.isdigit():
            parsed = int(value)
    if parsed is None or abs(parsed) >= _INT_LIMIT:
        raise _bad(f"{field} is not an integer in range")
    return parsed


def scale_money(raw: int, digits: int) -> Decimal:
    """``raw / 10^digits`` built from the digit tuple: no context rounding can apply."""
    if not 0 <= digits <= MAX_MONEY_DIGITS:
        raise _bad(f"moneyDigits out of range: {digits}")
    sign, numerals, _exponent = Decimal(raw).as_tuple()
    return Decimal((sign, numerals, -digits))


def parse_price(value: object, field: str) -> Decimal:
    """A price from JSON (a double) as Decimal via ``str``: the shortest decimal that
    round-trips the double (1.085, not 1.0849999...), as the MT5 adapter does. No float
    arithmetic ever touches it; callers quantize to the symbol's digits."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise _bad(f"{field} is not a number")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise _bad(f"{field} is not a number") from None
    if not parsed.is_finite():
        raise _bad(f"{field} is not a finite number")
    return parsed


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
    if not value.is_finite():
        raise _bad("money value is not a finite number")
    try:
        with localcontext(_WIDE):
            stored = value.quantize(_CENTS, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise _bad("money value too large to store") from None
    if abs(stored) >= _STORED_LIMIT:
        raise _bad("money value too large to store")
    return stored

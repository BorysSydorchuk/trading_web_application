"""Raw MT5 records as returned by an `Mt5Source` (real terminal or fixture).

"Raw" means: field names follow the MetaTrader5 package, times are the server's wall-clock
epoch seconds exactly as MT5 reports them (NOT UTC, see `app.mt5.convert`), enum fields are
MT5 integer codes, and numbers are `Decimal` made from MT5 floats with ``Decimal(str(x))``.

``str(float)`` is the shortest decimal that round-trips the double, so a price MT5 stores
as 1.085 becomes Decimal("1.085"), not 1.0849999999999999644... Prices are additionally
quantized to the symbol's ``digits`` in the adapter (`app.mt5.convert`), which removes any
residual float noise (e.g. 1.0850000000000002) on computed prices.

The same dataclasses serialise to/from the fixture JSON (decimals as strings), so a recorded
fixture is exactly what the real source returned.
"""

from __future__ import annotations

import dataclasses
import math
import types
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Union, get_args, get_origin, get_type_hints

ZERO = Decimal(0)


def to_decimal(value: object) -> Decimal:
    """MT5 number (float/int) or fixture string -> Decimal, via ``str`` for floats."""
    if isinstance(value, bool):
        raise ValueError(f"expected a number, got {value!r}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number from MT5: {value!r}")
        result = Decimal(str(value))
    elif isinstance(value, int | str):
        try:
            result = Decimal(value)
        except InvalidOperation:
            raise ValueError(f"not a decimal number: {value!r}") from None
    else:
        raise ValueError(f"expected a number, got {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"non-finite number: {value!r}")
    return result


@dataclass(frozen=True)
class RawAccountInfo:
    login: int
    server: str
    balance: Decimal
    equity: Decimal
    currency: str


@dataclass(frozen=True)
class RawSymbolSpec:
    """symbol_info(): trade_contract_size, trade_tick_size, trade_tick_value, volume_*."""

    name: str
    digits: int
    contract_size: Decimal
    tick_size: Decimal
    tick_value: Decimal
    volume_min: Decimal
    volume_step: Decimal
    volume_max: Decimal
    currency_profit: str
    currency_margin: str


@dataclass(frozen=True)
class RawDeal:
    """history_deals_get() TradeDeal. ``time``/``time_msc``: server wall clock epoch."""

    ticket: int
    order: int
    position_id: int
    time: int
    type: int  # ENUM_DEAL_TYPE
    entry: int  # ENUM_DEAL_ENTRY
    volume: Decimal
    price: Decimal
    profit: Decimal
    symbol: str
    time_msc: int = 0
    reason: int = 0  # ENUM_DEAL_REASON
    magic: int = 0
    commission: Decimal = ZERO
    swap: Decimal = ZERO
    fee: Decimal = ZERO
    sl: Decimal | None = None  # not present in every terminal build
    tp: Decimal | None = None


@dataclass(frozen=True)
class RawOrder:
    """history_orders_get() TradeOrder (only what trade building needs)."""

    ticket: int
    position_id: int
    time_setup: int
    type: int  # ENUM_ORDER_TYPE
    state: int  # ENUM_ORDER_STATE
    volume_initial: Decimal
    price_open: Decimal
    sl: Decimal
    tp: Decimal
    symbol: str
    time_setup_msc: int = 0


@dataclass(frozen=True)
class RawPosition:
    """positions_get() TradePosition. ``identifier`` is the position id used by deals."""

    ticket: int
    identifier: int
    time: int
    type: int  # 0 buy, 1 sell
    volume: Decimal
    price_open: Decimal
    sl: Decimal
    tp: Decimal
    price_current: Decimal
    profit: Decimal
    symbol: str
    time_msc: int = 0
    swap: Decimal = ZERO


type RawRecord = RawAccountInfo | RawSymbolSpec | RawDeal | RawOrder | RawPosition


def to_json_dict(record: RawRecord) -> dict[str, Any]:
    """Fixture JSON shape: decimals as strings, ints and strings as-is."""
    out: dict[str, Any] = {}
    for f in dataclasses.fields(record):
        value = getattr(record, f.name)
        out[f.name] = str(value) if isinstance(value, Decimal) else value
    return out


def _parse_value(hint: Any, value: object, where: str) -> object:
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        options = get_args(hint)
        if value is None and type(None) in options:
            return None
        inner = [o for o in options if o is not type(None)]
        if len(inner) == 1:
            return _parse_value(inner[0], value, where)
        raise TypeError(f"{where}: unsupported field type {hint!r}")  # pragma: no cover
    if hint is Decimal:
        return to_decimal(value)
    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where}: expected an integer, got {value!r}")
        return value
    if hint is str:
        if not isinstance(value, str):
            raise ValueError(f"{where}: expected a string, got {value!r}")
        return value
    raise TypeError(f"{where}: unsupported field type {hint!r}")  # pragma: no cover


def from_json_dict[R: RawRecord](cls: type[R], data: Mapping[str, object]) -> R:
    """Inverse of `to_json_dict`. Keys starting with ``_`` are comments and ignored."""
    hints = get_type_hints(cls)
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(k for k in data if k not in names and not k.startswith("_"))
    if unknown:
        raise ValueError(f"{cls.__name__}: unknown fields {unknown}")
    kwargs: dict[str, Any] = {
        k: _parse_value(hints[k], v, f"{cls.__name__}.{k}") for k, v in data.items() if k in names
    }
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise ValueError(f"{cls.__name__}: {exc}") from None

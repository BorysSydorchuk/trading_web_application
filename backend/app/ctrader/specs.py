"""cTrader symbol specs -> the platform-neutral `RawSymbolSpec` (docs/api.md phase c, c1). Pure.

Inputs: ProtoOALightSymbol (2114: ``symbolId``, ``symbolName``, ``baseAssetId``,
``quoteAssetId``), ProtoOASymbol (2116: ``digits``, ``lotSize``, ``minVolume``,
``stepVolume``, ``maxVolume``; volumes and lot size in cents of a unit) and the asset names
(2112). The result goes into the existing ``symbol_specs`` columns (DECISIONS 2026-11-24):

- ``contract_size = lotSize / 100``; ``tick_size = point = 10^-digits``;
- ``volume_min/step/max = minVolume/stepVolume/maxVolume / lotSize`` (lots, exact Decimal);
- ``currency_profit`` = quote asset name, ``currency_margin`` = base asset name;
- ``tick_value = tick_value_loss = contract_size * tick_size`` (in the profit currency).

A symbol with a missing, non-integer or non-positive field (``digits`` may be 0), an unknown
asset, a blank name or a value ``symbol_specs`` (NUMERIC(20,8)) cannot hold exactly gives
None and one WARNING: a spec is never written half.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from decimal import Context, Decimal, Inexact, InvalidOperation
from typing import Any, Final

from app.ctrader.errors import CtraderError
from app.ctrader.money import parse_int
from app.mt5.types import RawSymbolSpec

logger = logging.getLogger(__name__)

_EXACT: Final = Context(prec=60, traps=[Inexact, InvalidOperation])
_CENTS_PER_UNIT: Final = Decimal(100)
# symbol_specs numbers are NUMERIC(20,8): at most 8 places and 12 integer digits.
_STORED_PLACES: Final = Decimal("0.00000001")
_STORED_LIMIT: Final = Decimal(10) ** 12
_MAX_DIGITS: Final = 8  # tick size 10^-digits must fit the 8 places


class _UnusableError(ValueError):
    """Why one symbol cannot become a spec (logged once, never raised to the caller)."""


def _int_field(raw: Mapping[str, Any], key: str, *, minimum: int) -> int:
    value = raw.get(key)
    if value is None:
        raise _UnusableError(f"{key} is missing")
    try:
        parsed = parse_int(value, key)
    except CtraderError:
        raise _UnusableError(f"{key} {value!r} is not an integer") from None
    if parsed < minimum:
        raise _UnusableError(f"{key} {parsed} is below {minimum}")
    return parsed


def _asset(light: Mapping[str, Any], key: str, assets: Mapping[int, str]) -> str:
    value = light.get(key)
    try:
        asset_id = parse_int(value, key) if value is not None else None
    except CtraderError:
        asset_id = None
    name = assets.get(asset_id) if asset_id is not None else None
    if name is None or not name.strip():
        raise _UnusableError(f"{key} {value!r} is not a known asset")
    return name.strip()


def _storable(value: Decimal, name: str) -> Decimal:
    # The limit first: quantize below then needs at most 20 significant digits.
    if (
        not value.is_finite()
        or abs(value) >= _STORED_LIMIT
        or value.quantize(_STORED_PLACES) != value
    ):
        raise _UnusableError(f"{name} {value} does not fit symbol_specs exactly")
    return value


def _divide(numerator: int, denominator: int | Decimal, name: str) -> Decimal:
    try:
        value = _EXACT.divide(Decimal(numerator), Decimal(denominator))
    except (Inexact, InvalidOperation):
        raise _UnusableError(f"{name} is not an exact decimal") from None
    return _storable(value, name)


def _spec(
    name: str, light: Mapping[str, Any], full: Mapping[str, Any], assets: Mapping[int, str]
) -> RawSymbolSpec:
    digits = _int_field(full, "digits", minimum=0)
    if digits > _MAX_DIGITS:
        raise _UnusableError(f"digits {digits} is above {_MAX_DIGITS}")
    lot_size = _int_field(full, "lotSize", minimum=1)
    volumes = [_int_field(full, key, minimum=1) for key in ("minVolume", "stepVolume", "maxVolume")]
    quote = _asset(light, "quoteAssetId", assets)
    base = _asset(light, "baseAssetId", assets)
    contract_size = _divide(lot_size, _CENTS_PER_UNIT, "contract size")
    tick_size = Decimal(1).scaleb(-digits)
    tick_value = _storable(_EXACT.multiply(contract_size, tick_size), "tick value")
    volume_min, volume_step, volume_max = (
        _divide(volume, lot_size, label)
        for volume, label in zip(volumes, ("volume min", "volume step", "volume max"), strict=True)
    )
    return RawSymbolSpec(
        name=name,
        digits=digits,
        contract_size=contract_size,
        tick_size=tick_size,
        tick_value=tick_value,
        volume_min=volume_min,
        volume_step=volume_step,
        volume_max=volume_max,
        currency_profit=quote,
        currency_margin=base,
        point=tick_size,
        tick_value_loss=tick_value,
    )


def spec_from_symbol(
    light: Mapping[str, Any], full: Mapping[str, Any], assets: Mapping[int, str]
) -> RawSymbolSpec | None:
    """The spec of one symbol, or None (one WARNING) when any field is unusable."""
    raw_name = light.get("symbolName")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        logger.warning("cTrader symbol id %r has no name; no spec", light.get("symbolId"))
        return None
    try:
        return _spec(name, light, full, assets)
    except _UnusableError as exc:
        logger.warning("cTrader symbol %s: %s; spec skipped", name, exc)
        return None

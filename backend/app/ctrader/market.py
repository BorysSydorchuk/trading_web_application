"""cTrader symbol specs and conversion quotes of one account, read-only (phase c, c1 + c2).

Every cycle: the symbol list (2114). When the specs are due (`MarketRequest.refresh_specs`:
first cycle, then at most hourly; or a traded symbol without a stored spec): the asset names
(2112) and the full symbols (2116) of the config symbols (resolved as for MT5, aliases and
firm overrides included), the symbols of this read's trades and the conversion pairs.

Conversion (same rule as MT5, M5-09): for every cross profit currency the pair is picked
among the cTrader symbol names (`pick_conversion_pair`: direct ``<P><A>`` -> ask, inverse
``<A><P>`` -> 1 / bid). Its quote is the last BID and the last ASK tick (2145) in the last
`FRESH_WINDOW`, else in the last `FALLBACK_WINDOW`; the quote time is the later of the two.
A pair without a usable quote is a WARNING and gets no quote (the stored rate row stays).
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from app.config_files.symbols import SymbolsConfig
from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import check_account, ms_from_utc
from app.ctrader.money import parse_int
from app.ctrader.specs import spec_from_symbol
from app.ctrader.ticks import ASK, BID, CtTick, last_tick
from app.domain.fx import ConversionPair, RateQuote, is_cross_currency, pick_conversion_pair
from app.domain.symbols import resolve_broker_symbol
from app.mt5.types import RawSymbolSpec

logger = logging.getLogger(__name__)

FRESH_WINDOW: Final = timedelta(minutes=60)
FALLBACK_WINDOW: Final = timedelta(days=3)

Light = Mapping[str, Any]


@dataclass(frozen=True)
class MarketRequest:
    """What to read for one account. ``known_specs``: broker names with a stored spec;
    ``stored_currencies``: their profit currencies (upper-case)."""

    symbols: SymbolsConfig
    firm: str | None
    account_currency: str
    refresh_specs: bool
    known_specs: frozenset[str] = frozenset()
    stored_currencies: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MarketRead:
    specs: Mapping[str, RawSymbolSpec] = field(default_factory=dict)  # by broker name
    quotes: tuple[RateQuote, ...] = ()  # at = the later of the BID/ASK ticks


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


def _objects(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _bad(f"{key} is not a list of objects")
    return value


async def _light_symbols(connection: CtraderConnection, ctid: int) -> dict[str, Light]:
    payload = await connection.request(
        p.SYMBOLS_LIST_REQ,
        {"ctidTraderAccountId": ctid, "includeArchivedSymbols": False},
        p.SYMBOLS_LIST_RES,
    )
    check_account(payload, ctid)
    found: dict[str, Light] = {}
    for item in _objects(payload, "symbol"):
        name = item.get("symbolName")
        if isinstance(name, str) and name.strip() and item.get("symbolId") is not None:
            found.setdefault(name.strip(), item)
    return found


async def _assets(connection: CtraderConnection, ctid: int) -> dict[int, str]:
    payload = await connection.request(
        p.ASSET_LIST_REQ, {"ctidTraderAccountId": ctid}, p.ASSET_LIST_RES
    )
    check_account(payload, ctid)
    return {
        parse_int(item.get("assetId"), "assetId"): item["name"]
        for item in _objects(payload, "asset")
        if isinstance(item.get("name"), str)
    }


async def _full_symbols(
    connection: CtraderConnection, ctid: int, symbol_ids: Collection[int]
) -> dict[int, Light]:
    payload = await connection.request(
        p.SYMBOL_BY_ID_REQ,
        {"ctidTraderAccountId": ctid, "symbolId": sorted(symbol_ids)},
        p.SYMBOL_BY_ID_RES,
    )
    check_account(payload, ctid)
    return {parse_int(i.get("symbolId"), "symbolId"): i for i in _objects(payload, "symbol")}


def _config_names(request: MarketRequest, listing: Collection[str], ctid: int) -> set[str]:
    found: set[str] = set()
    for name in request.symbols.names:
        broker = resolve_broker_symbol(request.symbols, name, request.firm, listing)
        if broker is None:
            logger.warning("cTrader account %s: symbol %s not at the broker; no spec", ctid, name)
        else:
            found.add(broker)
    return found


def _quote_currency(light: Light, assets: Mapping[int, str]) -> str | None:
    try:
        name = assets.get(parse_int(light.get("quoteAssetId"), "quoteAssetId"))
    except CtraderError:
        return None
    return name.strip().upper() if name and name.strip() else None


def _pairs(
    currencies: Collection[str], account_currency: str, listing: Collection[str], ctid: int
) -> dict[str, ConversionPair]:
    pairs: dict[str, ConversionPair] = {}
    for currency in sorted(c for c in currencies if is_cross_currency(c, account_currency)):
        pair = pick_conversion_pair(currency, account_currency, listing)
        if pair is None:
            logger.warning(
                "cTrader account %s: no %s->%s conversion pair (%s%s or %s%s); no rate stored",
                ctid, currency, account_currency, currency, account_currency, account_currency,
                currency,
            )  # fmt: skip
            continue
        if len(pair.candidates) > 1:
            logger.warning(
                "cTrader account %s: several %s->%s pair candidates (%s); using %s",
                ctid, currency, account_currency, ", ".join(pair.candidates), pair.pair,
            )  # fmt: skip
        pairs[currency] = pair
    return pairs


async def _read_specs(
    connection: CtraderConnection,
    ctid: int,
    listing: Mapping[str, Light],
    assets: Mapping[int, str],
    names: Collection[str],
) -> dict[str, RawSymbolSpec]:
    ids = {parse_int(listing[name].get("symbolId"), "symbolId"): name for name in names}
    full = await _full_symbols(connection, ctid, ids)
    specs: dict[str, RawSymbolSpec] = {}
    for symbol_id, name in sorted(ids.items()):
        details = full.get(symbol_id)
        if details is None:
            logger.warning("cTrader account %s: symbol %s has no full spec", ctid, name)
            continue
        spec = spec_from_symbol(listing[name], details, assets)
        if spec is not None:
            specs[spec.name] = spec
    return specs


async def _side(
    connection: CtraderConnection, ctid: int, symbol_id: int, kind: int, now: datetime
) -> CtTick | None:
    to_ms = ms_from_utc(now)
    for window in (FRESH_WINDOW, FALLBACK_WINDOW):
        tick = await last_tick(connection, ctid, symbol_id, kind, ms_from_utc(now - window), to_ms)
        if tick is not None:
            return tick
    return None


async def _quote(
    connection: CtraderConnection,
    ctid: int,
    target: tuple[str, str, ConversionPair],
    symbol_id: int,
    now: datetime,
) -> RateQuote | None:
    """One pair's quote; a failed or empty read is a WARNING and None."""
    currency, account_currency, pair = target
    try:
        bid = await _side(connection, ctid, symbol_id, BID, now)
        ask = await _side(connection, ctid, symbol_id, ASK, now) if bid is not None else None
    except CtraderError as exc:
        logger.warning("cTrader account %s: ticks of %s not read: %s", ctid, pair.pair, exc)
        return None
    if bid is None or ask is None or bid.price <= 0 or ask.price <= 0:
        logger.warning(
            "cTrader account %s: no usable BID/ASK tick of %s in the last %s days; %s->%s "
            "rate kept",
            ctid, pair.pair, FALLBACK_WINDOW.days, currency, account_currency,
        )  # fmt: skip
        return None
    at = max(bid.time, ask.time)
    return RateQuote(currency, account_currency, pair, bid.price, ask.price, at)


async def read_market(
    connection: CtraderConnection,
    ctid: int,
    request: MarketRequest,
    trade_names: Collection[str],
    now: datetime,
) -> MarketRead:
    """Specs (when due) and conversion quotes of one account. Raises `CtraderError` only for
    the symbol, asset or spec answers; a pair's tick failure is logged and skipped."""
    listing = await _light_symbols(connection, ctid)
    traded = {name for name in trade_names if name in listing}
    refresh = request.refresh_specs or not traded <= request.known_specs
    wanted = traded | _config_names(request, listing, ctid) if refresh and listing else set()
    assets = await _assets(connection, ctid) if wanted else {}
    read_currencies = {_quote_currency(listing[name], assets) for name in wanted}
    currencies = request.stored_currencies | {c for c in read_currencies if c is not None}
    account_currency = request.account_currency.strip().upper()
    pairs = _pairs(currencies, account_currency, listing, ctid)
    specs: dict[str, RawSymbolSpec] = {}
    if wanted:
        names = wanted | {pair.pair for pair in pairs.values()}
        specs = await _read_specs(connection, ctid, listing, assets, names)
    quotes: list[RateQuote] = []
    for currency, pair in pairs.items():
        symbol_id = parse_int(listing[pair.pair].get("symbolId"), "symbolId")
        quote = await _quote(connection, ctid, (currency, account_currency, pair), symbol_id, now)
        if quote is not None:
            quotes.append(quote)
    return MarketRead(specs=specs, quotes=tuple(quotes))

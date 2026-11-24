"""cTrader trading history, read-only: open positions (2124), deals (2133), symbols (2114/2116).

Field names follow the Open API JSON (ProtoOADeal, ProtoOAClosePositionDetail, ProtoOAPosition,
ProtoOALightSymbol, ProtoOASymbol). Times are UTC epoch milliseconds and become aware UTC
datetimes here. Volumes stay integers in cTrader units (cents of the base unit, as the API
sends them); lots are computed in `app.ctrader.convert` with the symbol's ``lotSize``. Money
is scaled by ``moneyDigits`` (`app.ctrader.money`), prices go through ``str`` -> Decimal.

Enum fields may arrive as numbers or names; both are accepted.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.money import parse_int, parse_price, scale_money

logger = logging.getLogger(__name__)

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SIDES: Final[dict[object, str]] = {1: "buy", "BUY": "buy", 2: "sell", "SELL": "sell"}
# ProtoOADealStatus: only executed deals move a position.
_FILLED: Final = frozenset({2, "FILLED", 3, "PARTIALLY_FILLED"})
_POSITION_OPEN: Final = frozenset({1, "POSITION_STATUS_OPEN"})
# The read range starts this much earlier: a deal at the edge must never be dropped (upserts
# are idempotent). It ends at "now", never in the future; a position opened after that (or
# ahead of the local clock) is outside the range and is read on the next cycle.
RANGE_PAD: Final = timedelta(minutes=1)
# Upper bound of one history read (DB-open trades older than this are not re-read).
MAX_READ_SPAN: Final = timedelta(days=370)
# hasMore: the window is halved until every part fits; a 1 ms window that still has more
# (or this depth) is a bad answer, never an endless loop.
MAX_SPLIT_DEPTH: Final = 40


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


def utc_from_ms(value: object, name: str) -> datetime:
    return _EPOCH + timedelta(milliseconds=parse_int(value, name))


def ms_from_utc(at: datetime) -> int:
    if at.tzinfo is None:
        raise ValueError("a cTrader time must be aware UTC")
    return (at - _EPOCH) // timedelta(milliseconds=1)


def check_account(payload: Mapping[str, Any], ctid: int) -> None:
    """Data from another account's answer must never be stored."""
    if (
        "ctidTraderAccountId" in payload
        and parse_int(payload["ctidTraderAccountId"], "ctidTraderAccountId") != ctid
    ):
        raise _bad("answer for another account")


@dataclass(frozen=True)
class CtSymbol:
    symbol_id: int
    name: str
    digits: int | None = None
    lot_size: int | None = None  # cTrader volume units per lot (ProtoOASymbol.lotSize)


@dataclass(frozen=True)
class CloseDetail:
    """ProtoOAClosePositionDetail: the realized money of the closed volume."""

    gross_profit: Decimal
    swap: Decimal
    commission: Decimal
    fee: Decimal  # pnlConversionFee, 0 when absent
    closed_volume: int | None


@dataclass(frozen=True)
class CtDeal:
    deal_id: int
    order_id: int
    position_id: int
    symbol_id: int
    side: str  # "buy" | "sell"
    volume: int  # filled volume, cTrader units
    price: Decimal
    time: datetime  # executionTimestamp, aware UTC
    close: CloseDetail | None  # set on a closing deal


@dataclass(frozen=True)
class CtPosition:
    position_id: int
    symbol_id: int
    side: str
    volume: int
    open_time: datetime
    sl: Decimal | None
    tp: Decimal | None


@dataclass(frozen=True)
class HistoryRequest:
    """What to read for one account. ``open_trades``: DB-open position id -> open time."""

    window_from: datetime
    to: datetime
    open_trades: Mapping[int, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class TradingRead:
    request: HistoryRequest
    read_from: datetime
    read_to: datetime
    deals: tuple[CtDeal, ...]
    positions: tuple[CtPosition, ...]
    symbols: Mapping[int, CtSymbol]


def _side(value: object, name: str) -> str:
    side = _SIDES.get(value) if isinstance(value, int | str) else None
    if side is None:
        raise _bad(f"{name} is not BUY or SELL")
    return side


def _list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise _bad(f"{key} is not a list")
    return value


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _bad(f"{name} is not an object")
    return value


def _optional_price(raw: Mapping[str, Any], key: str) -> Decimal | None:
    value = raw.get(key)
    if value is None:
        return None
    price = parse_price(value, key)
    return price if price != 0 else None


def _close_detail(raw: object, deal_digits: object) -> CloseDetail:
    detail = _object(raw, "closePositionDetail")
    digits = parse_int(detail.get("moneyDigits", deal_digits), "moneyDigits")

    def money(key: str, *, required: bool = True) -> Decimal:
        value = detail.get(key)
        if value is None and not required:
            return Decimal(0)
        return scale_money(parse_int(value, key), digits)

    closed = detail.get("closedVolume")
    return CloseDetail(
        gross_profit=money("grossProfit"),
        swap=money("swap", required=False),
        commission=money("commission", required=False),
        fee=money("pnlConversionFee", required=False),
        closed_volume=parse_int(closed, "closedVolume") if closed is not None else None,
    )


def parse_deal(entry: object) -> CtDeal | None:
    """One ProtoOADeal; None for a deal that did not execute (rejected, missed, no fill)."""
    raw = _object(entry, "deal")
    if raw.get("dealStatus") not in _FILLED:
        return None
    filled = raw.get("filledVolume")
    volume = parse_int(filled if filled is not None else raw.get("volume"), "filledVolume")
    if volume <= 0:
        return None
    close = raw.get("closePositionDetail")
    return CtDeal(
        deal_id=parse_int(raw.get("dealId"), "dealId"),
        order_id=parse_int(raw.get("orderId"), "orderId"),
        position_id=parse_int(raw.get("positionId"), "positionId"),
        symbol_id=parse_int(raw.get("symbolId"), "symbolId"),
        side=_side(raw.get("tradeSide"), "tradeSide"),
        volume=volume,
        price=parse_price(raw.get("executionPrice"), "executionPrice"),
        time=utc_from_ms(raw.get("executionTimestamp"), "executionTimestamp"),
        close=_close_detail(close, raw.get("moneyDigits")) if close is not None else None,
    )


def parse_position(entry: object) -> CtPosition | None:
    """One ProtoOAPosition of the reconcile answer; None unless it is open with volume."""
    raw = _object(entry, "position")
    status = raw.get("positionStatus")
    if status is not None and status not in _POSITION_OPEN:
        return None
    trade = _object(raw.get("tradeData"), "tradeData")
    volume = parse_int(trade.get("volume"), "volume")
    if volume <= 0:
        return None
    return CtPosition(
        position_id=parse_int(raw.get("positionId"), "positionId"),
        symbol_id=parse_int(trade.get("symbolId"), "symbolId"),
        side=_side(trade.get("tradeSide"), "tradeSide"),
        volume=volume,
        open_time=utc_from_ms(trade.get("openTimestamp"), "openTimestamp"),
        sl=_optional_price(raw, "stopLoss"),
        tp=_optional_price(raw, "takeProfit"),
    )


# --- requests --------------------------------------------------------------------------


async def read_positions(connection: CtraderConnection, ctid: int) -> tuple[CtPosition, ...]:
    payload = await connection.request(
        p.RECONCILE_REQ, {"ctidTraderAccountId": ctid}, p.RECONCILE_RES
    )
    check_account(payload, ctid)
    parsed = (parse_position(item) for item in _list(payload, "position"))
    return tuple(position for position in parsed if position is not None)


async def _read_window(
    connection: CtraderConnection, ctid: int, lo: int, hi: int, found: dict[int, CtDeal], depth: int
) -> None:
    payload = await connection.request(
        p.DEAL_LIST_REQ,
        {"ctidTraderAccountId": ctid, "fromTimestamp": lo, "toTimestamp": hi},
        p.DEAL_LIST_RES,
        historical=True,
    )
    check_account(payload, ctid)
    if payload.get("hasMore") is True:
        if hi <= lo or depth >= MAX_SPLIT_DEPTH:
            raise _bad("deal list still has more deals in the smallest window")
        mid = (lo + hi) // 2
        await _read_window(connection, ctid, lo, mid, found, depth + 1)
        await _read_window(connection, ctid, mid + 1, hi, found, depth + 1)
        return
    for item in _list(payload, "deal"):
        deal = parse_deal(item)
        if deal is not None:
            found[deal.deal_id] = deal


async def read_deals(
    connection: CtraderConnection, ctid: int, from_ms: int, to_ms: int
) -> tuple[CtDeal, ...]:
    """Every executed deal in ``from_ms..to_ms`` (inclusive), in windows of at most one week;
    a window answered with ``hasMore`` is split in halves. Unique by dealId, time ordered."""
    found: dict[int, CtDeal] = {}
    lo = from_ms
    while lo <= to_ms:
        hi = min(lo + p.MAX_DEAL_WINDOW_MS - 1, to_ms)
        await _read_window(connection, ctid, lo, hi, found, 0)
        lo = hi + 1
    return tuple(sorted(found.values(), key=lambda d: (d.time, d.deal_id)))


def _symbol_names(payload: Mapping[str, Any]) -> dict[int, str]:
    names: dict[int, str] = {}
    for key, name_key in (("archivedSymbol", "name"), ("symbol", "symbolName")):
        for item in _list(payload, key):
            raw = _object(item, key)
            name = raw.get(name_key)
            if isinstance(name, str) and name.strip():
                names[parse_int(raw.get("symbolId"), "symbolId")] = name.strip()
    return names


async def symbol_ids_by_name(connection: CtraderConnection, ctid: int) -> dict[str, int]:
    """Broker name -> symbol id of every symbol (2114, archived included)."""
    listing = await connection.request(
        p.SYMBOLS_LIST_REQ,
        {"ctidTraderAccountId": ctid, "includeArchivedSymbols": True},
        p.SYMBOLS_LIST_RES,
    )
    check_account(listing, ctid)
    return {name: symbol_id for symbol_id, name in sorted(_symbol_names(listing).items())}


def _optional_int(raw: Mapping[str, Any], key: str) -> int | None:
    value = raw.get(key)
    return parse_int(value, key) if value is not None else None


async def read_symbols(
    connection: CtraderConnection, ctid: int, symbol_ids: Collection[int]
) -> dict[int, CtSymbol]:
    """Name (2114, archived included) and digits/lot size (2116) of the given symbols.

    A symbol without a name is left out (its positions are skipped, visibly)."""
    if not symbol_ids:
        return {}
    listing = await connection.request(
        p.SYMBOLS_LIST_REQ,
        {"ctidTraderAccountId": ctid, "includeArchivedSymbols": True},
        p.SYMBOLS_LIST_RES,
    )
    check_account(listing, ctid)
    names = _symbol_names(listing)
    wanted = sorted(symbol_ids)
    details = await connection.request(
        p.SYMBOL_BY_ID_REQ, {"ctidTraderAccountId": ctid, "symbolId": wanted}, p.SYMBOL_BY_ID_RES
    )
    check_account(details, ctid)
    specs: dict[int, tuple[int | None, int | None]] = {}
    for item in _list(details, "symbol"):
        raw = _object(item, "symbol")
        specs[parse_int(raw.get("symbolId"), "symbolId")] = (
            _optional_int(raw, "digits"),
            _optional_int(raw, "lotSize"),
        )
    out: dict[int, CtSymbol] = {}
    for symbol_id in wanted:
        if symbol_id not in names:
            logger.warning("cTrader account %s: symbol id %s has no name", ctid, symbol_id)
            continue
        digits, lot_size = specs.get(symbol_id, (None, None))
        out[symbol_id] = CtSymbol(symbol_id, names[symbol_id], digits, lot_size)
    return out


def read_range(
    request: HistoryRequest, positions: Collection[CtPosition], now: datetime
) -> tuple[datetime, datetime]:
    """From the earliest of the window, the DB-open trades and the open positions (so every
    position to build has its entry deal), padded back, at most `MAX_READ_SPAN` back; it
    ends at ``now`` (the request time if later)."""
    to = max(request.to, now)
    starts = [request.window_from, *request.open_trades.values()]
    starts.extend(position.open_time for position in positions)
    return max(min(starts) - RANGE_PAD, to - MAX_READ_SPAN), to


async def read_trading(
    connection: CtraderConnection, ctid: int, request: HistoryRequest, now: datetime
) -> TradingRead:
    """Positions first, then the deals up to after that answer: a position opened in between
    is then in the deals (open for one cycle at worst), never missing its entry."""
    positions = await read_positions(connection, ctid)
    read_from, read_to = read_range(request, positions, now)
    deals = await read_deals(connection, ctid, ms_from_utc(read_from), ms_from_utc(read_to))
    symbol_ids = {d.symbol_id for d in deals} | {position.symbol_id for position in positions}
    symbols = await read_symbols(connection, ctid, symbol_ids)
    return TradingRead(request, read_from, read_to, deals, positions, symbols)

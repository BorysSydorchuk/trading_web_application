"""cTrader order history of one position (2183, read-only) and its initial SL (pure rule).

cTrader deals carry no SL, so a position the app never saw open (closed before the
connection, while the app was off, or between two syncs) had no initial SL. Its orders do:

1. The opening order: the order named by the entry deal (``orderId``), else the earliest
   non-closing executed order that is not a protective one. Its absolute ``stopLoss``, else
   its ``relativeStopLoss`` (1/100000 of a price unit) from its ``executionPrice`` (the
   trade's entry price when absent): BUY entry - distance, SELL entry + distance.
2. Otherwise the earliest protective order (``STOP_LOSS_TAKE_PROFIT``) of the position: its
   ``stopLoss``, else its ``stopPrice``. The order history keeps an order's last state, so a
   protective order moved later shows the moved price, not the first one (DECISIONS).

A candidate counts only on the loss side of the entry price (below for a buy, above for a
sell); a stop at or beyond the entry (breakeven, locked profit) is never an initial SL.
Prices go through ``str`` -> Decimal and are quantized to the symbol's digits.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import CtDeal, TradingRead, check_account, ms_from_utc, utc_from_ms
from app.ctrader.money import parse_int, parse_price
from app.mt5.convert import quantize_price

logger = logging.getLogger(__name__)

_TYPES: Final[dict[object, str]] = {
    1: "market",
    "MARKET": "market",
    2: "limit",
    "LIMIT": "limit",
    3: "stop",
    "STOP": "stop",
    4: "protective",
    "STOP_LOSS_TAKE_PROFIT": "protective",
    5: "market_range",
    "MARKET_RANGE": "market_range",
    6: "stop_limit",
    "STOP_LIMIT": "stop_limit",
}
_FILLED: Final = frozenset({2, "ORDER_STATUS_FILLED"})
_SIDES: Final[dict[object, str]] = {1: "buy", "BUY": "buy", 2: "sell", "SELL": "sell"}
RELATIVE_SCALE: Final = Decimal(100_000)
# Same splitting rule as the deal list: halve a window answered with hasMore.
MAX_SPLIT_DEPTH: Final = 40

# A dropped session/connection or an access problem concerns the whole read (the caller's
# retry rule and status), never one skipped position.
_RAISE: Final = frozenset(
    {
        CtraderErrorCode.ACCOUNT_DISCONNECTED,
        CtraderErrorCode.CONNECTION_FAILED,
        CtraderErrorCode.TIMEOUT,
        CtraderErrorCode.TOKEN_INVALID,
        CtraderErrorCode.TOKEN_EXPIRED,
        CtraderErrorCode.NOT_AUTHORIZED,
        CtraderErrorCode.CLIENT_AUTH_FAILED,
    }
)

SlKind = Literal["opening", "protective"]


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


@dataclass(frozen=True)
class CtOrder:
    order_id: int
    position_id: int | None
    kind: str  # market | limit | stop | protective | market_range | stop_limit | unknown
    side: str | None
    filled: bool  # FILLED status or an executed volume
    closing: bool
    created: datetime | None  # tradeData.openTimestamp
    execution_price: Decimal | None
    stop_loss: Decimal | None  # absolute
    relative_stop_loss: int | None  # 1/100000 of a price unit
    stop_price: Decimal | None


@dataclass(frozen=True)
class InitialStop:
    sl: Decimal
    kind: SlKind
    order_id: int


def _price(raw: Mapping[str, Any], key: str) -> Decimal | None:
    value = raw.get(key)
    if value is None:
        return None
    price = parse_price(value, key)
    return price if price != 0 else None


def _int(raw: Mapping[str, Any], key: str) -> int | None:
    value = raw.get(key)
    return parse_int(value, key) if value is not None else None


def parse_order(entry: object) -> CtOrder:
    if not isinstance(entry, dict):
        raise _bad("order is not an object")
    trade = entry.get("tradeData", {})
    if not isinstance(trade, dict):
        raise _bad("tradeData is not an object")
    executed = _int(entry, "executedVolume")
    created = trade.get("openTimestamp")
    relative = _int(entry, "relativeStopLoss")
    return CtOrder(
        order_id=parse_int(entry.get("orderId"), "orderId"),
        position_id=_int(entry, "positionId"),
        kind=_TYPES.get(entry.get("orderType"), "unknown"),
        side=_SIDES.get(trade.get("tradeSide")),
        filled=entry.get("orderStatus") in _FILLED or (executed is not None and executed > 0),
        closing=entry.get("closingOrder") is True,
        created=utc_from_ms(created, "openTimestamp") if created is not None else None,
        execution_price=_price(entry, "executionPrice"),
        stop_loss=_price(entry, "stopLoss"),
        relative_stop_loss=relative if relative else None,
        stop_price=_price(entry, "stopPrice"),
    )


# --- the rule (pure) -------------------------------------------------------------------


def _on_loss_side(side: str, entry: Decimal, sl: Decimal) -> bool:
    return sl < entry if side == "buy" else sl > entry


def _order_key(order: CtOrder) -> tuple[bool, datetime | None, int]:
    # Orders without a creation time go last; ties by id (ids grow with time).
    return (order.created is None, order.created, order.order_id)


def _opening_order(orders: Sequence[CtOrder], opening_order_id: int | None) -> CtOrder | None:
    named = [o for o in orders if opening_order_id is not None and o.order_id == opening_order_id]
    if named:
        return named[0]
    candidates = [o for o in orders if o.filled and not o.closing and o.kind != "protective"]
    return min(candidates, key=_order_key, default=None)


def _opening_sl(order: CtOrder, side: str, entry: Decimal) -> Decimal | None:
    if order.stop_loss is not None:
        return order.stop_loss
    if order.relative_stop_loss is None:
        return None
    base = order.execution_price if order.execution_price is not None else entry
    distance = Decimal(order.relative_stop_loss) / RELATIVE_SCALE
    return base - distance if side == "buy" else base + distance


def initial_stop(
    orders: Iterable[CtOrder],
    *,
    side: str,
    entry_price: Decimal,
    digits: int | None,
    opening_order_id: int | None = None,
) -> InitialStop | None:
    """The position's initial SL from its orders (module doc), or None."""
    own = list(orders)
    opening = _opening_order(own, opening_order_id)
    if opening is not None:
        sl = _opening_sl(opening, side, entry_price)
        if sl is not None:
            sl = quantize_price(sl, digits)
            if _on_loss_side(side, entry_price, sl):
                return InitialStop(sl, "opening", opening.order_id)
    for order in sorted((o for o in own if o.kind == "protective"), key=_order_key):
        price = order.stop_loss if order.stop_loss is not None else order.stop_price
        if price is None:
            continue
        sl = quantize_price(price, digits)
        if _on_loss_side(side, entry_price, sl):
            return InitialStop(sl, "protective", order.order_id)
    return None


# --- request ---------------------------------------------------------------------------


async def _read_window(
    connection: CtraderConnection,
    ctid: int,
    position_id: int,
    lo: int,
    hi: int,
    found: dict[int, CtOrder],
    depth: int,
) -> None:
    payload = await connection.request(
        p.ORDER_LIST_BY_POSITION_REQ,
        {
            "ctidTraderAccountId": ctid,
            "positionId": position_id,
            "fromTimestamp": lo,
            "toTimestamp": hi,
        },
        p.ORDER_LIST_BY_POSITION_RES,
        historical=True,
    )
    check_account(payload, ctid)
    if payload.get("hasMore") is True:
        if hi <= lo or depth >= MAX_SPLIT_DEPTH:
            raise _bad("order list still has more orders in the smallest window")
        mid = (lo + hi) // 2
        await _read_window(connection, ctid, position_id, lo, mid, found, depth + 1)
        await _read_window(connection, ctid, position_id, mid + 1, hi, found, depth + 1)
        return
    items = payload.get("order", [])
    if not isinstance(items, list):
        raise _bad("order is not a list")
    for item in items:
        order = parse_order(item)
        if order.position_id is None or order.position_id == position_id:
            found[order.order_id] = order


async def read_position_orders(
    connection: CtraderConnection, ctid: int, position_id: int, start: datetime, end: datetime
) -> tuple[CtOrder, ...]:
    """Every order of the position last updated in ``start..end``, in windows of at most one
    week (as the deal list); a window answered with ``hasMore`` is split in halves."""
    found: dict[int, CtOrder] = {}
    lo, to_ms = ms_from_utc(start), ms_from_utc(end)
    while lo <= to_ms:
        hi = min(lo + p.MAX_DEAL_WINDOW_MS - 1, to_ms)
        await _read_window(connection, ctid, position_id, lo, hi, found, 0)
        lo = hi + 1
    return tuple(sorted(found.values(), key=_order_key))


# --- during a sync ---------------------------------------------------------------------

# Positions whose orders one sync reads at most (one historical request each, 5/s limit);
# more is logged and left to `python -m app.tools.backfill_ctrader_sl`.
MAX_ORDER_READS: Final = 10
ORDER_PAD: Final = timedelta(minutes=1)


@dataclass(frozen=True)
class _Unseen:
    position_id: int
    side: str
    entry_price: Decimal
    opening_order_id: int
    symbol_id: int
    start: datetime
    end: datetime


def _vwap(deals: Sequence[CtDeal]) -> Decimal:
    volume = sum(d.volume for d in deals)
    return sum((d.price * d.volume for d in deals), Decimal(0)) / volume


def unseen_closed(read: TradingRead) -> list[_Unseen]:
    """Positions closed in this read that the app never saw open: not reported open now, not
    open in the DB, with their entry deal(s) in the read. Oldest first."""
    by_position: dict[int, list[CtDeal]] = defaultdict(list)
    for deal in read.deals:
        by_position[deal.position_id].append(deal)
    live = {position.position_id for position in read.positions}
    out: list[_Unseen] = []
    for pid, own in by_position.items():
        if pid in live or pid in read.request.open_trades:
            continue
        entries = sorted((d for d in own if d.close is None), key=lambda d: (d.time, d.deal_id))
        if not entries or all(d.close is None for d in own):
            continue
        first = entries[0]
        out.append(
            _Unseen(
                position_id=pid,
                side=first.side,
                entry_price=_vwap(entries),
                opening_order_id=first.order_id,
                symbol_id=first.symbol_id,
                start=first.time - ORDER_PAD,
                end=max(d.time for d in own) + ORDER_PAD,
            )
        )
    return sorted(out, key=lambda u: (u.start, u.position_id))


async def read_opening_stops(
    connection: CtraderConnection, ctid: int, read: TradingRead
) -> dict[int, Decimal]:
    """Initial SL by position id of the read's `unseen_closed` positions (at most
    `MAX_ORDER_READS`). A position whose orders cannot be read is logged and skipped: its
    trade stays ``needs_sl`` (visible), the backfill tool can read it later. A dropped
    connection or session is raised (the caller's retry rule)."""
    unseen = unseen_closed(read)
    if len(unseen) > MAX_ORDER_READS:
        logger.warning(
            "cTrader account %s: %s closed position(s) without a known SL, orders read for %s;"
            " run backfill_ctrader_sl for the rest",
            ctid,
            len(unseen),
            MAX_ORDER_READS,
        )
    found: dict[int, Decimal] = {}
    for item in unseen[:MAX_ORDER_READS]:
        try:
            orders = await read_position_orders(
                connection, ctid, item.position_id, item.start, item.end
            )
        except CtraderError as exc:
            if exc.code in _RAISE:
                raise
            logger.warning(
                "cTrader account %s: orders of position %s not read: %s",
                ctid,
                item.position_id,
                exc.code.value,
            )
            continue
        symbol = read.symbols.get(item.symbol_id)
        stop = initial_stop(
            orders,
            side=item.side,
            entry_price=item.entry_price,
            digits=symbol.digits if symbol is not None else None,
            opening_order_id=item.opening_order_id,
        )
        if stop is not None:
            found[item.position_id] = stop.sl
            logger.info(
                "cTrader account %s: position %s initial SL %s from %s order %s",
                ctid,
                item.position_id,
                stop.sl,
                stop.kind,
                stop.order_id,
            )
    return found

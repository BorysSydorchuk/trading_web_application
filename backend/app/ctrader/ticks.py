"""cTrader tick data, read-only (2145 GetTickDataReq; docs/api.md phase c, c2).

ASSUMPTION (Open API docs, to confirm on the first live run): ``ProtoOATickData.timestamp``
(epoch ms UTC) and ``.tick`` (price * 100000) are absolute in the first entry and deltas to
the previous entry after it. Deltas are signed, so either time order decodes; the latest tick
is picked by time, never by position. Prices are exact Decimals (no float).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import check_account, utc_from_ms
from app.ctrader.money import parse_int, scale_money

logger = logging.getLogger(__name__)

BID: Final = 1  # ProtoOAQuoteType
ASK: Final = 2
PRICE_DIGITS: Final = 5  # tick prices are integers in 1/100000


@dataclass(frozen=True)
class CtTick:
    time: datetime  # aware UTC
    price: Decimal


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


def decode_ticks(entries: Sequence[object]) -> tuple[CtTick, ...]:
    """Delta-decoded ticks in the order received; raises ``bad_response`` on a bad entry."""
    out: list[CtTick] = []
    at = price = 0
    for entry in entries:
        if not isinstance(entry, dict) or "timestamp" not in entry or "tick" not in entry:
            raise _bad("tick entry lacks timestamp or tick")
        at += parse_int(entry["timestamp"], "timestamp")
        price += parse_int(entry["tick"], "tick")
        try:
            time = utc_from_ms(at, "timestamp")
        except OverflowError:
            raise _bad("tick timestamp out of range") from None
        out.append(CtTick(time, scale_money(price, PRICE_DIGITS)))
    return tuple(out)


async def last_tick(
    connection: CtraderConnection, ctid: int, symbol_id: int, kind: int, from_ms: int, to_ms: int
) -> CtTick | None:
    """The latest BID or ASK tick in ``from_ms..to_ms`` (a historical request), or None."""
    payload = await connection.request(
        p.TICK_DATA_REQ,
        {
            "ctidTraderAccountId": ctid,
            "symbolId": symbol_id,
            "type": kind,
            "fromTimestamp": from_ms,
            "toTimestamp": to_ms,
        },
        p.TICK_DATA_RES,
        historical=True,
    )
    check_account(payload, ctid)
    entries = payload.get("tickData", [])
    if not isinstance(entries, list):
        raise _bad("tickData is not a list")
    if payload.get("hasMore") is True:
        # ASSUMPTION: the answer then holds part of the range; its latest tick is used.
        logger.debug("cTrader ticks of symbol %s: more than one answer holds", symbol_id)
    ticks = decode_ticks(entries)
    return max(ticks, key=lambda tick: tick.time) if ticks else None

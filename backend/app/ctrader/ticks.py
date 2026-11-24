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
from app.ctrader.history import check_account, ms_from_utc, utc_from_ms
from app.ctrader.money import parse_int, scale_money

logger = logging.getLogger(__name__)

BID: Final = 1  # ProtoOAQuoteType
ASK: Final = 2
PRICE_DIGITS: Final = 5  # tick prices are integers in 1/100000
# A partial (hasMore) answer is followed by asking again after its latest tick, at most so often.
MAX_TICK_PAGES: Final = 8


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


async def tick_page(
    connection: CtraderConnection, ctid: int, symbol_id: int, kind: int, from_ms: int, to_ms: int
) -> tuple[tuple[CtTick, ...], bool]:
    """One 2145 answer (a historical request): the BID or ASK ticks in ``from_ms..to_ms``
    and its ``hasMore`` (True: the answer holds only part of the range)."""
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
    return decode_ticks(entries), payload.get("hasMore") is True


async def last_tick(
    connection: CtraderConnection, ctid: int, symbol_id: int, kind: int, from_ms: int, to_ms: int
) -> CtTick | None:
    """The latest BID or ASK tick in ``from_ms..to_ms`` (a historical request), or None.

    A partial (``hasMore``) answer may hold either end of the range (the order is not
    confirmed yet), so the range is asked again after the latest tick seen until an answer
    is complete. Still partial after `MAX_TICK_PAGES` answers: a WARNING and None, never a
    tick that may be stale."""
    latest: CtTick | None = None
    for _ in range(MAX_TICK_PAGES):
        ticks, has_more = await tick_page(connection, ctid, symbol_id, kind, from_ms, to_ms)
        if ticks:
            newest = max(ticks, key=lambda tick: tick.time)
            latest = newest if latest is None or newest.time > latest.time else latest
        if not has_more:
            return latest
        if latest is None:
            break
        from_ms = ms_from_utc(latest.time) + 1
        if from_ms > to_ms:
            return latest
    logger.warning(
        "cTrader ticks of symbol %s: latest tick not found in %d partial answers",
        symbol_id, MAX_TICK_PAGES,
    )  # fmt: skip
    return None

"""MAE / MFE of cTrader trades from 2145 ticks and 2137 M1 trendbars, read-only (phase c, c5).

The definitions, targets and store rules are those of MT5 M8-16 (`app.services.excursions`,
`app.domain.excursion`); only the price reading differs:

- a trade shorter than 2 h: BID and ASK ticks over the whole trade, merged by timestamp
  (`merge_bid_ask`; source TICKS);
- otherwise: ticks for the entry and exit minutes and M1 trendbars in between (source
  M1_TICKS). Trendbars are BID only, so a short adds the median ASK-BID spread of its entry
  and exit tick samples to every bar (docs/DECISIONS.md 2026-11-24); a long uses them as is.

`fetch_ctrader_series` reads every target under one time limit and never raises: a failed
target is recorded as an attempt (``Fetched.failed``) and the next one is read; a read cut
off by the limit, a timeout, a dropped connection or a rate limit also ends the step.

ASSUMPTIONS (Open API docs, to confirm on the first live run): 2137 takes
``ctidTraderAccountId``, ``symbolId``, ``period`` (1 = M1), ``fromTimestamp`` and
``toTimestamp`` (ms, by bar start); the answer lists ``trendbar[]`` with an absolute ``low``
and unsigned ``deltaHigh`` above it (prices in 1/100000) and ``utcTimestampInMinutes`` (bar
start, epoch minutes UTC). A ``hasMore`` answer (ticks or bars) holds only part of its range:
the range is halved until every part fits, at most `MAX_PAGES` requests per window; beyond
that the series is incomplete (retried, then unavailable as for MT5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from typing import Any, Final

from app.ctrader import protocol as p
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import (
    CtSymbol,
    check_account,
    ms_from_utc,
    symbol_ids_by_name,
    utc_from_ms,
)
from app.ctrader.money import parse_int, scale_money
from app.ctrader.ticks import ASK, BID, PRICE_DIGITS, CtTick, tick_page
from app.domain.excursion import PriceSample, bar
from app.models.enums import Direction, ExcursionSource
from app.services.excursions import TICKS_ONLY_BELOW, ExcursionTarget, Fetched, Series

logger = logging.getLogger(__name__)

# Seconds for MAE/MFE per account and cycle (MT5: 20 s; the whole cTrader read has 45 s).
# Not Final: read at call time (`BUDGET_S` of this module), so a test can change it.
BUDGET_S: float = 8.0
M1_PERIOD: Final = 1  # ProtoOATrendbarPeriod.M1
# One trendbar request spans at most a day of M1 bars (~1440 bars, well below the 1 MB frame).
BAR_CHUNK: Final = timedelta(days=1)
# hasMore splits of one tick side or one bar chunk; beyond: the series is incomplete.
MAX_PAGES: Final = 16
_MINUTE: Final = timedelta(minutes=1)
_MINUTE_MS: Final = 60_000
_ZERO: Final = Decimal(0)
# The connection is blocked or throttled: never hold up the rest of the cycle.
_STOP_STEP: Final = frozenset(
    {
        CtraderErrorCode.TIMEOUT,
        CtraderErrorCode.CONNECTION_FAILED,
        CtraderErrorCode.RATE_LIMITED,
        CtraderErrorCode.ACCOUNT_DISCONNECTED,
    }
)


@dataclass(frozen=True)
class CtBar:
    """One BID M1 trendbar: start of the minute (aware UTC), low and high."""

    time: datetime
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class ExcursionRequest:
    """What one account measures this cycle (chosen before the read by `excursion_targets`).
    ``points``: the stored ``symbol_specs.point`` by broker name (used when the read's own
    symbol digits are missing)."""

    targets: tuple[ExcursionTarget, ...] = ()
    points: Mapping[str, Decimal] = field(default_factory=dict)


def _bad(message: str) -> CtraderError:
    return CtraderError(CtraderErrorCode.BAD_RESPONSE, message)


# --- pure ------------------------------------------------------------------------------------


def _bar_of(entry: object) -> CtBar:
    keys = ("low", "deltaHigh", "utcTimestampInMinutes")
    if not isinstance(entry, dict) or any(key not in entry for key in keys):
        raise _bad("trendbar lacks low, deltaHigh or utcTimestampInMinutes")
    low = parse_int(entry["low"], "low")
    delta_high = parse_int(entry["deltaHigh"], "deltaHigh")
    minutes = parse_int(entry["utcTimestampInMinutes"], "utcTimestampInMinutes")
    if low <= 0 or delta_high < 0:
        raise _bad("trendbar price out of range")
    try:
        start = utc_from_ms(minutes * _MINUTE_MS, "utcTimestampInMinutes")
    except OverflowError:
        raise _bad("trendbar time out of range") from None
    return CtBar(start, scale_money(low, PRICE_DIGITS), scale_money(low + delta_high, PRICE_DIGITS))


def decode_trendbars(entries: Sequence[object]) -> tuple[CtBar, ...]:
    """Trendbars in the order received; raises ``bad_response`` on a malformed entry."""
    return tuple(_bar_of(entry) for entry in entries)


def merge_bid_ask(bids: Sequence[CtTick], asks: Sequence[CtTick]) -> tuple[PriceSample, ...]:
    """One sample per distinct timestamp: the quotes of that instant (several at the same
    millisecond give the sample's high/low), the other side carried forward from its last
    quote. No sample until both sides were quoted once."""
    events = sorted(
        [(t.time, BID, t.price) for t in bids] + [(t.time, ASK, t.price) for t in asks],
        key=lambda event: (event[0], event[1]),  # stable: input order within one instant
    )
    samples: list[PriceSample] = []
    last: dict[int, Decimal] = {}
    for at, group in groupby(events, key=lambda event: event[0]):
        now: dict[int, list[Decimal]] = {BID: [], ASK: []}
        for _at, side, price in group:
            now[side].append(price)
            last[side] = price
        if BID not in last or ASK not in last:
            continue
        bid = now[BID] or [last[BID]]
        ask = now[ASK] or [last[ASK]]
        samples.append(PriceSample(at, max(bid), min(bid), max(ask), min(ask)))
    return tuple(samples)


def median_spread(samples: Sequence[PriceSample]) -> Decimal | None:
    """Median ASK-BID of the samples (the mean of the two middle ones for an even count)."""
    spreads = sorted(sample.ask_low - sample.bid_low for sample in samples)
    if not spreads:
        return None
    middle = len(spreads) // 2
    if len(spreads) % 2:
        return spreads[middle]
    return (spreads[middle - 1] + spreads[middle]) / 2


def bar_samples(bars: Sequence[CtBar], spread: Decimal) -> tuple[PriceSample, ...]:
    """BID bars as samples; the ASK side is the bar plus ``spread`` (price units)."""
    return tuple(bar(b.time, b.high, b.low, spread) for b in bars)


# --- reading ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    connection: CtraderConnection
    ctid: int
    symbol_id: int


class _Pages:
    """Requests left for one window (hasMore splits)."""

    def __init__(self, limit: int = MAX_PAGES) -> None:
        self.left = limit


PageReader = Callable[[int, int], Awaitable[tuple[Sequence[Any], bool]]]


async def _all_pages(read: PageReader, lo: int, hi: int, pages: _Pages) -> tuple[list[Any], bool]:
    """Everything in ``lo..hi`` (ms): a ``hasMore`` answer is replaced by its two halves.
    The flag is False when the page limit or a 1 ms window still had more."""
    if pages.left <= 0:
        return [], False  # the limit was used by an earlier part of this window
    pages.left -= 1
    items, has_more = await read(lo, hi)
    if not has_more:
        return list(items), True
    if hi <= lo or pages.left < 2:
        logger.warning("cTrader prices %s..%s: too many for %s requests", lo, hi, MAX_PAGES)
        return list(items), False
    middle = (lo + hi) // 2
    first, first_whole = await _all_pages(read, lo, middle, pages)
    second, second_whole = await _all_pages(read, middle + 1, hi, pages)
    return first + second, first_whole and second_whole


def _ceil_ms(at: datetime) -> int:
    return ms_from_utc(at) + (1 if at.microsecond % 1000 else 0)


async def _side(
    source: _Source, kind: int, start: datetime, end: datetime
) -> tuple[list[CtTick], bool]:
    async def read(lo: int, hi: int) -> tuple[Sequence[CtTick], bool]:
        return await tick_page(source.connection, source.ctid, source.symbol_id, kind, lo, hi)

    return await _all_pages(read, ms_from_utc(start), _ceil_ms(end), _Pages())


async def _quotes(
    source: _Source, start: datetime, end: datetime
) -> tuple[tuple[PriceSample, ...], bool]:
    """BID + ASK samples in ``start..end`` (inclusive); ASK is read only when a BID was."""
    bids, bids_whole = await _side(source, BID, start, end)
    if not bids:
        return (), bids_whole
    asks, asks_whole = await _side(source, ASK, start, end)
    return merge_bid_ask(bids, asks), bids_whole and asks_whole


async def _trendbar_page(source: _Source, lo: int, hi: int) -> tuple[Sequence[CtBar], bool]:
    payload = await source.connection.request(
        p.TRENDBARS_REQ,
        {
            "ctidTraderAccountId": source.ctid,
            "symbolId": source.symbol_id,
            "period": M1_PERIOD,
            "fromTimestamp": lo,
            "toTimestamp": hi,
        },
        p.TRENDBARS_RES,
        historical=True,
    )
    check_account(payload, source.ctid)
    if "symbolId" in payload and parse_int(payload["symbolId"], "symbolId") != source.symbol_id:
        raise _bad("trendbars of another symbol")
    entries = payload.get("trendbar", [])
    if not isinstance(entries, list):
        raise _bad("trendbar is not a list")
    return decode_trendbars(entries), payload.get("hasMore") is True


async def _bars(source: _Source, start: datetime, end: datetime) -> tuple[list[CtBar], bool]:
    """The M1 bars lying fully inside [start, end) (both whole minutes), by chunks of
    `BAR_CHUNK`. A bar overlapping the entry or exit minute is never used."""

    async def read(lo: int, hi: int) -> tuple[Sequence[CtBar], bool]:
        return await _trendbar_page(source, lo, hi)

    found: dict[datetime, CtBar] = {}
    whole = True
    last_start = end - _MINUTE
    chunk_from = start
    while chunk_from <= last_start:
        chunk_to = min(chunk_from + BAR_CHUNK - _MINUTE, last_start)
        bars, chunk_whole = await _all_pages(
            read, ms_from_utc(chunk_from), ms_from_utc(chunk_to), _Pages()
        )
        whole = whole and chunk_whole
        found.update((b.time, b) for b in bars if start <= b.time and b.time + _MINUTE <= end)
        chunk_from = chunk_to + _MINUTE
    return [found[at] for at in sorted(found)], whole


def _floor_minute(at: datetime) -> datetime:
    return at.replace(second=0, microsecond=0)


def _ceil_minute(at: datetime) -> datetime:
    floor = _floor_minute(at)
    return floor if floor == at else floor + _MINUTE


async def series_for_ctrader(
    connection: CtraderConnection,
    ctid: int,
    symbol_id: int,
    target: ExcursionTarget,
    point: Decimal | None,
    now: datetime,
) -> Series:
    """The samples of one trade (raises `CtraderError` on a refused or malformed answer)."""
    source = _Source(connection, ctid, symbol_id)
    end = target.close_time or now
    start = target.open_time
    middle_from, middle_to = _ceil_minute(start), _floor_minute(end)
    if end - start < TICKS_ONLY_BELOW or middle_to <= middle_from:
        samples, whole = await _quotes(source, start, end)
        return Series(target, end, samples, ExcursionSource.TICKS, point, whole)
    first, first_whole = await _quotes(source, start, middle_from)
    last, last_whole = await _quotes(source, middle_to, end)
    complete = bool(first) and bool(last) and first_whole and last_whole
    middle: tuple[PriceSample, ...] = ()
    if complete or target.close_time is None:  # a closed incomplete trade only retries
        bars, bars_whole = await _bars(source, middle_from, middle_to)
        complete = complete and bars_whole
        spread = _ZERO
        if target.direction is Direction.SELL:
            spread = max(_ZERO, median_spread((*first, *last)) or _ZERO)
        middle = bar_samples(bars, spread)
    return Series(target, end, (*first, *middle, *last), ExcursionSource.M1_TICKS, point, complete)


async def fetch_ctrader_series(
    connection: CtraderConnection,
    ctid: int,
    targets: Iterable[ExcursionTarget],
    symbol_ids: Mapping[str, int],
    points: Mapping[str, Decimal | None],
    now: datetime,
    budget_s: float | None = None,
) -> Fetched:
    """Read the series of ``targets`` within ``budget_s`` (default `BUDGET_S`, read now);
    never raises. With no time left nothing is sent."""
    fetched = Fetched(series=[], failed=[])
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (BUDGET_S if budget_s is None else budget_s)
    for target in targets:
        if loop.time() >= deadline:
            logger.info("cTrader MAE/MFE: time budget used, the rest waits for the next cycle")
            break
        symbol_id = symbol_ids.get(target.broker_symbol)
        if symbol_id is None:
            fetched.failed.append(target.trade_id)
            logger.warning(
                "cTrader MAE/MFE of trade %s: symbol %s not found at the broker",
                target.trade_id, target.broker_symbol,
            )  # fmt: skip
            continue
        point = points.get(target.broker_symbol)
        try:
            async with asyncio.timeout_at(deadline):
                series = await series_for_ctrader(connection, ctid, symbol_id, target, point, now)
        except TimeoutError:
            fetched.failed.append(target.trade_id)
            logger.warning(
                "cTrader MAE/MFE of trade %s cut off by its time limit; the rest waits for "
                "the next cycle",
                target.trade_id,
            )
            break
        except CtraderError as exc:
            fetched.failed.append(target.trade_id)
            logger.warning("cTrader MAE/MFE of trade %s not read: %s", target.trade_id, exc)
            if exc.code in _STOP_STEP:
                break
            continue
        except Exception:
            fetched.failed.append(target.trade_id)
            logger.exception("cTrader MAE/MFE of trade %s not read", target.trade_id)
            continue
        fetched.series.append(series)
    return fetched


def _point_from_digits(digits: int | None) -> Decimal | None:
    if digits is None or not 0 <= digits <= PRICE_DIGITS + 3:
        return None
    return Decimal(1).scaleb(-digits)


async def read_excursions(
    connection: CtraderConnection,
    ctid: int,
    request: ExcursionRequest,
    symbols: Mapping[int, CtSymbol],
    now: datetime,
    until: float,
) -> Fetched:
    """Symbol ids and points of the targets, then `fetch_ctrader_series` until ``until``
    (loop time). Symbols outside this read's trades are looked up in one 2114. Never raises."""
    ids = {symbol.name: symbol.symbol_id for symbol in symbols.values()}
    points: dict[str, Decimal | None] = dict(request.points)
    for symbol in symbols.values():
        points[symbol.name] = _point_from_digits(symbol.digits) or points.get(symbol.name)
    missing = {target.broker_symbol for target in request.targets} - ids.keys()
    loop = asyncio.get_running_loop()
    if missing:
        try:
            async with asyncio.timeout_at(until):
                listing = await symbol_ids_by_name(connection, ctid)
            ids.update({name: listing[name] for name in missing if name in listing})
        except (TimeoutError, CtraderError) as exc:
            logger.warning(
                "cTrader account %s: MAE/MFE symbols not listed: %s", ctid,
                exc if isinstance(exc, CtraderError) else "time limit",
            )  # fmt: skip
    budget = max(0.0, until - loop.time())
    return await fetch_ctrader_series(
        connection, ctid, request.targets, ids, points, now, budget_s=budget
    )

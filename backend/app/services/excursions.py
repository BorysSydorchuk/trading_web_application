"""MAE / MFE of trades from MT5 price history (M8-16; docs/api.md "M8-16").

Three steps, so the sync can run the MT5 part inside its own connection:

1. ``excursion_targets`` (DB, before the sync connects): closed trades of the last
   ``RECENT_DAYS`` without a final value and open trades, each at most once per
   ``RETRY_EVERY`` (``excursion_at`` = last attempt), least recently tried first.
2. ``fetch_series`` (MT5, read-only, inside the connection): ticks for trades shorter than
   2 h; otherwise ticks for the entry and exit minutes and M1 bars in between. A time budget
   per account; a failed read is recorded as an attempt; a timeout ends the step (the
   source must not be blocked for the next sync). Never raises.
3. ``store_excursions`` (DB, one savepoint per trade): `compute_excursion` and the trade's
   ``mfe_*`` / ``mae_*`` columns. Without (complete) history a trade is retried; only one
   closed more than ``UNAVAILABLE_AFTER`` ago is marked ``unavailable``. Open trades are never.

Only the ``mfe_*``, ``mae_*`` and ``excursion_*`` columns are ever written.
"""

from __future__ import annotations

import logging
import time as monotonic_time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.broker_time import Conversion, server_msc_to_wall, server_to_utc, utc_to_server
from app.domain.excursion import Excursion, PriceSample, bar, compute_excursion, tick
from app.models import Trade
from app.models.enums import Direction, ExcursionSource, ExcursionStatus
from app.mt5.convert import server_epoch
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.source import Mt5Source, PriceHistory
from app.mt5.types import RawSymbolSpec

logger = logging.getLogger(__name__)

RECENT_DAYS = 7
MAX_CLOSED = 5
MAX_OPEN = 5
RETRY_EVERY = timedelta(minutes=10)  # also the refresh of an open trade's running value
UNAVAILABLE_AFTER = timedelta(hours=24)  # MT5 may still be downloading a fresh history
TICKS_ONLY_BELOW = timedelta(hours=2)
BUDGET_S = 20.0
_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class ExcursionTarget:
    trade_id: int
    broker_symbol: str
    direction: Direction
    entry_price: Decimal
    initial_sl: Decimal | None
    open_time: datetime
    close_time: datetime | None  # None = open position: measured until "now"


@dataclass(frozen=True)
class Series:
    target: ExcursionTarget
    end_time: datetime
    samples: tuple[PriceSample, ...]
    source: ExcursionSource
    point: Decimal | None
    # False: the entry or exit minute had no ticks (where the SL/TP hit is): not final yet.
    complete: bool = True


@dataclass
class Fetched:
    """What the store step needs: the series read, and the trades whose read failed."""

    series: list[Series]
    failed: list[int]


def target_of(trade: Trade) -> ExcursionTarget:
    return ExcursionTarget(
        trade_id=trade.id,
        broker_symbol=trade.broker_symbol,
        direction=Direction(trade.direction),
        entry_price=trade.entry_price,
        initial_sl=trade.initial_sl,
        open_time=trade.open_time,
        close_time=trade.close_time,
    )


def excursion_targets(session: Session, account_id: int, now: datetime) -> list[ExcursionTarget]:
    """What the next sync of ``account_id`` should measure (see module doc). Never raises."""
    done = (ExcursionStatus.FINAL.value, ExcursionStatus.UNAVAILABLE.value)
    due = or_(Trade.excursion_at.is_(None), Trade.excursion_at < now - RETRY_EVERY)
    tried_first = (Trade.excursion_at.asc().nulls_first(), Trade.id)
    try:
        closed = session.scalars(
            select(Trade)
            .where(
                Trade.account_id == account_id,
                Trade.close_time.is_not(None),
                Trade.close_time >= now - timedelta(days=RECENT_DAYS),
                or_(Trade.excursion_status.is_(None), Trade.excursion_status.not_in(done)),
                due,
            )
            .order_by(*tried_first)
            .limit(MAX_CLOSED)
        ).all()
        running = session.scalars(
            select(Trade)
            .where(Trade.account_id == account_id, Trade.close_time.is_(None), due)
            .order_by(*tried_first)
            .limit(MAX_OPEN)
        ).all()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("MAE/MFE targets of account %s not read; skipped", account_id)
        return []
    return [target_of(t) for t in (*closed, *running)]


def _ceil_minute(dt: datetime) -> datetime:
    floor = dt.replace(second=0, microsecond=0)
    return floor if floor == dt else floor + _MINUTE


def _floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _epochs(start: datetime, end: datetime, conversion: Conversion) -> tuple[int, int]:
    """UTC range -> server epochs (inclusive; the end is rounded up to the next second)."""
    lo = server_epoch(utc_to_server(start, conversion).replace(microsecond=0))
    hi_wall = utc_to_server(end, conversion)
    hi = server_epoch(hi_wall.replace(microsecond=0)) + (1 if hi_wall.microsecond else 0)
    return lo, hi


def _ticks(
    source: PriceHistory, symbol: str, start: datetime, end: datetime, conversion: Conversion
) -> list[PriceSample]:
    lo, hi = _epochs(start, end, conversion)
    return [
        tick(server_to_utc(server_msc_to_wall(t.time_msc), conversion), t.bid, t.ask)
        for t in source.ticks(symbol, lo, hi)
    ]


def _bars(
    source: PriceHistory,
    symbol: str,
    start: datetime,
    end: datetime,
    conversion: Conversion,
    point: Decimal | None,
) -> list[PriceSample]:
    """M1 bars covering exactly [start, end) (both full minutes)."""
    lo, hi = _epochs(start, end - _MINUTE, conversion)
    spread_unit = point if point is not None and point > 0 else Decimal(0)
    samples = []
    for raw in source.rates_m1(symbol, lo, hi):
        begin = server_to_utc(raw.time, conversion)
        if begin < start or begin + _MINUTE > end:
            continue  # never a bar that overlaps the entry or exit minute
        samples.append(bar(begin, raw.high, raw.low, raw.spread * spread_unit))
    return samples


def series_for(
    source: PriceHistory,
    target: ExcursionTarget,
    conversion: Conversion,
    point: Decimal | None,
    now: datetime,
) -> Series:
    """The samples of one trade (raises `Mt5Error` on an MT5 read failure)."""
    end = target.close_time or now
    start = target.open_time
    symbol = target.broker_symbol
    middle_from, middle_to = _ceil_minute(start), _floor_minute(end)
    if end - start < TICKS_ONLY_BELOW or middle_to <= middle_from:
        ticks = tuple(_ticks(source, symbol, start, end, conversion))
        return Series(target, end, ticks, ExcursionSource.TICKS, point)
    first = _ticks(source, symbol, start, middle_from, conversion)
    middle = _bars(source, symbol, middle_from, middle_to, conversion, point)
    last = _ticks(source, symbol, middle_to, end, conversion)
    complete = bool(first) and bool(last)
    return Series(target, end, (*first, *middle, *last), ExcursionSource.M1_TICKS, point, complete)


def _point(
    source: Mt5Source,
    symbol: str,
    specs: Mapping[str, RawSymbolSpec],
    cache: dict[str, RawSymbolSpec | None],
) -> Decimal | None:
    """The symbol's point; a symbol outside the sync's specs is looked up once (read-only)."""
    if symbol not in cache:
        known = specs.get(symbol)
        cache[symbol] = known if known is not None else source.symbol_spec(symbol)
    found = cache[symbol]
    return found.point if found is not None else None


def fetch_series(
    source: Mt5Source,
    targets: Iterable[ExcursionTarget],
    conversion: Conversion,
    specs: Mapping[str, RawSymbolSpec],
    now: datetime,
    budget_s: float = BUDGET_S,
) -> Fetched:
    """Read the price series of ``targets`` while connected; never raises."""
    fetched = Fetched(series=[], failed=[])
    if not isinstance(source, PriceHistory):
        return fetched  # a source without price history (test fakes): no excursions
    started = monotonic_time.monotonic()
    cache: dict[str, RawSymbolSpec | None] = {}
    for target in targets:
        if monotonic_time.monotonic() - started > budget_s:
            logger.info("MAE/MFE: time budget used, the rest waits for the next sync")
            break
        try:
            point = _point(source, target.broker_symbol, specs, cache)
            fetched.series.append(series_for(source, target, conversion, point, now))
        except Mt5Error as exc:
            fetched.failed.append(target.trade_id)
            logger.warning("MAE/MFE of trade %s not read: %s", target.trade_id, exc)
            if exc.code is Mt5ErrorCode.TIMEOUT:
                break  # the source is blocked: never hold up the next sync
        except Exception:
            fetched.failed.append(target.trade_id)
            logger.exception("MAE/MFE of trade %s not read", target.trade_id)
    return fetched


Outcome = Literal["final", "running", "retry", "unavailable"]


def evaluate(series: Series, now: datetime) -> tuple[Outcome, Excursion | None]:
    """The one rule for what a series gives (worker store and backfill dry run alike)."""
    target = series.target
    result = compute_excursion(
        target.direction,
        target.entry_price,
        target.initial_sl,
        target.open_time,
        series.end_time,
        series.samples,
        series.point,
    )
    close = target.close_time
    if close is None:
        return ("running", result) if result is not None else ("retry", None)
    if result is None or not series.complete:
        # fresh history may still be downloading; after a day it will not come any more
        return ("unavailable" if now - close > UNAVAILABLE_AFTER else "retry"), None
    return "final", result


def _store_one(trade: Trade, series: Series, now: datetime) -> None:
    outcome, result = evaluate(series, now)
    trade.excursion_at = now  # the attempt, also when nothing is stored
    if outcome == "unavailable":
        trade.excursion_status = ExcursionStatus.UNAVAILABLE.value
        logger.warning("MAE/MFE of trade %s: MT5 has no (complete) history", trade.id)
    if result is None:
        return  # retry later, or unavailable
    trade.excursion_source = series.source.value
    trade.excursion_status = (
        ExcursionStatus.FINAL if outcome == "final" else ExcursionStatus.RUNNING
    ).value
    trade.mfe_price, trade.mfe_time = result.mfe_price, result.mfe_time
    trade.mfe_points, trade.mfe_r = result.mfe_points, result.mfe_r
    trade.mae_price, trade.mae_time = result.mae_price, result.mae_time
    trade.mae_points, trade.mae_r = result.mae_points, result.mae_r


def store_excursions(session: Session, fetched: Fetched, now: datetime) -> int:
    """Compute and store, one savepoint per trade; returns how many trades were written.
    Flushes, never commits."""
    written = 0
    for series in fetched.series:
        try:
            with session.begin_nested():
                trade = session.get(Trade, series.target.trade_id)
                if trade is not None:
                    _store_one(trade, series, now)
                    written += 1
        except Exception:
            logger.exception("MAE/MFE of trade %s not stored", series.target.trade_id)
    for trade_id in fetched.failed:
        try:
            with session.begin_nested():
                trade = session.get(Trade, trade_id)
                if trade is not None:
                    trade.excursion_at = now  # an attempt: retried after RETRY_EVERY
        except SQLAlchemyError:
            logger.exception("MAE/MFE attempt of trade %s not recorded", trade_id)
    session.flush()
    return written

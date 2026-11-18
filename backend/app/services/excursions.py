"""MAE / MFE of trades from MT5 price history (M8-16; docs/api.md "M8-16").

Three steps, so the sync can run the MT5 part inside its own connection:

1. ``excursion_targets`` (DB, before the sync connects): closed trades of the last
   ``RECENT_DAYS`` without a final value (oldest first, ``MAX_CLOSED`` per sync) and open
   trades whose running value is older than ``RUNNING_REFRESH``.
2. ``fetch_series`` (MT5, read-only, inside the connection): ticks for trades shorter than
   2 h; otherwise ticks for the entry and exit minutes and M1 bars in between. A time budget
   per account; a failure of one trade is logged and skipped (retried next sync).
3. ``store_excursions`` (DB): `compute_excursion` and the trade's ``mfe_*`` / ``mae_*``
   columns. No samples -> ``unavailable`` (the worker does not retry it; the backfill can).

Only the ``mfe_*``, ``mae_*`` and ``excursion_*`` columns are ever written.
"""

from __future__ import annotations

import logging
import time as monotonic_time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.broker_time import Conversion, server_msc_to_wall, server_to_utc, utc_to_server
from app.domain.excursion import PriceSample, bar, compute_excursion, tick
from app.models import Trade
from app.models.enums import Direction, ExcursionSource, ExcursionStatus
from app.mt5.convert import server_epoch
from app.mt5.errors import Mt5Error
from app.mt5.source import PriceHistory
from app.mt5.types import RawSymbolSpec

logger = logging.getLogger(__name__)

RECENT_DAYS = 7
MAX_CLOSED = 5
MAX_OPEN = 5
RUNNING_REFRESH = timedelta(minutes=15)
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
    """What the next sync of ``account_id`` should measure (see module doc)."""
    done = (ExcursionStatus.FINAL.value, ExcursionStatus.UNAVAILABLE.value)
    closed = session.scalars(
        select(Trade)
        .where(
            Trade.account_id == account_id,
            Trade.close_time.is_not(None),
            Trade.close_time >= now - timedelta(days=RECENT_DAYS),
            or_(Trade.excursion_status.is_(None), Trade.excursion_status.not_in(done)),
        )
        .order_by(Trade.close_time, Trade.id)
        .limit(MAX_CLOSED)
    ).all()
    running = session.scalars(
        select(Trade)
        .where(
            Trade.account_id == account_id,
            Trade.close_time.is_(None),
            or_(Trade.excursion_at.is_(None), Trade.excursion_at < now - RUNNING_REFRESH),
        )
        .order_by(Trade.open_time, Trade.id)
        .limit(MAX_OPEN)
    ).all()
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
        samples = _ticks(source, symbol, start, end, conversion)
        kind = ExcursionSource.TICKS
    else:
        samples = [
            *_ticks(source, symbol, start, middle_from, conversion),
            *_bars(source, symbol, middle_from, middle_to, conversion, point),
            *_ticks(source, symbol, middle_to, end, conversion),
        ]
        kind = ExcursionSource.M1_TICKS
    return Series(target, end, tuple(samples), kind, point)


def fetch_series(
    source: object,
    targets: Iterable[ExcursionTarget],
    conversion: Conversion,
    specs: Mapping[str, RawSymbolSpec],
    now: datetime,
    budget_s: float = BUDGET_S,
) -> list[Series]:
    """Read the price series of ``targets`` while connected; never raises."""
    if not isinstance(source, PriceHistory):
        return []  # a source without price history (test fakes): no excursions
    started = monotonic_time.monotonic()
    found: list[Series] = []
    for target in targets:
        if monotonic_time.monotonic() - started > budget_s:
            logger.info("MAE/MFE: time budget used, the rest waits for the next sync")
            break
        spec = specs.get(target.broker_symbol)
        point = spec.point if spec is not None else None
        try:
            found.append(series_for(source, target, conversion, point, now))
        except (Mt5Error, ValueError) as exc:
            logger.warning("MAE/MFE of trade %s not read: %s", target.trade_id, exc)
    return found


def store_excursions(session: Session, found: Iterable[Series], now: datetime) -> int:
    """Compute and store; returns how many trades changed. Flushes, never commits."""
    changed = 0
    for series in found:
        trade = session.get(Trade, series.target.trade_id)
        if trade is None:
            continue
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
        trade.excursion_at = now
        trade.excursion_source = series.source.value
        if result is None:
            trade.excursion_status = ExcursionStatus.UNAVAILABLE.value
            logger.warning("MAE/MFE of trade %s: MT5 has no price history", trade.id)
        else:
            trade.excursion_status = (
                ExcursionStatus.RUNNING if target.close_time is None else ExcursionStatus.FINAL
            ).value
            trade.mfe_price, trade.mfe_time = result.mfe_price, result.mfe_time
            trade.mfe_points, trade.mfe_r = result.mfe_points, result.mfe_r
            trade.mae_price, trade.mae_time = result.mae_price, result.mae_time
            trade.mae_points, trade.mae_r = result.mae_points, result.mae_r
        changed += 1
    session.flush()
    return changed

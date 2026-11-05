"""Bias alignment of a trade (PRD 6.6; DECISIONS 2026-11-05 M4, M4-04). Pure functions.

Which bias applies to a trade (all dates are local, Europe/Brussels from rules.yaml):

- daily: the trade's local open date. Opened before ``pre_ny_from`` (the start of the
  `premarket` session in rules.yaml, 11:00) → the `pre_london` entry; from then on → the
  `pre_ny` entry, falling back to the `pre_london` entry of the same day when the pre-NY note
  has no entry for the symbol (or there is no pre-NY note).
- weekly: the entry of the Monday of the open week; monthly: the entry of the 1st.

Mapping: bullish + buy / bearish + sell → aligned, the opposite → counter, neutral →
neutral_bias, no_trade → counter (trading against a planned no-trade day), no entry →
no_bias. A trade symbol matches a bias symbol by prefix, case-insensitively (broker suffixes
such as "GER40.cash", "XAUUSD+"); a symbol matching none is no_bias for all three.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.sessions import to_local
from app.models.enums import BiasAlignment, BiasDirection, BiasKind, Direction

# Used only when rules.yaml has no `premarket` session (the PRD boundary).
DEFAULT_PRE_NY_FROM = time(11, 0)
DAILY_KINDS = (BiasKind.PRE_LONDON, BiasKind.PRE_NY)


@dataclass(frozen=True, slots=True)
class AlignmentSettings:
    symbols: tuple[str, ...]  # bias.yaml symbol names
    tz: str  # IANA zone of the trading day (rules.yaml timezone)
    pre_ny_from: time  # local time from which a trade uses the pre_ny bias


@dataclass(frozen=True, slots=True)
class BiasPeriod:
    kind: BiasKind
    period_date: date


@dataclass(frozen=True, slots=True)
class BiasRef:
    """One stored bias entry as the alignment sees it."""

    note_id: int
    direction: str  # BiasDirection value


# (kind, period_date, casefolded bias symbol) -> entry. Build keys with `lookup_key`.
BiasLookup = Mapping[tuple[BiasKind, date, str], BiasRef]


@dataclass(frozen=True, slots=True)
class TradeBias:
    daily: BiasAlignment
    weekly: BiasAlignment
    monthly: BiasAlignment
    # Note whose entry decided each value; None when no_bias.
    daily_note_id: int | None = None
    weekly_note_id: int | None = None
    monthly_note_id: int | None = None


NO_BIAS = TradeBias(BiasAlignment.NO_BIAS, BiasAlignment.NO_BIAS, BiasAlignment.NO_BIAS)


def week_start(day: date) -> date:
    """Monday of the Mon-Sun week containing ``day`` (a Sunday belongs to the Monday before)."""
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def normalize_period(kind: BiasKind, day: date) -> date:
    """Stored period_date of a note: the day itself, its week's Monday or month's 1st."""
    if kind is BiasKind.WEEKLY:
        return week_start(day)
    if kind is BiasKind.MONTHLY:
        return month_start(day)
    return day


def period_utc_range(kind: BiasKind, period_date: date, tz: str) -> tuple[datetime, datetime]:
    """[start, end) UTC instants of the local day / week / month a note covers."""
    start_day = normalize_period(kind, period_date)
    if kind is BiasKind.WEEKLY:
        end_day = start_day + timedelta(days=7)
    elif kind is BiasKind.MONTHLY:
        end_day = (start_day + timedelta(days=32)).replace(day=1)
    else:
        end_day = start_day + timedelta(days=1)
    zone = ZoneInfo(tz)
    return (
        datetime.combine(start_day, time(0), tzinfo=zone).astimezone(UTC),
        datetime.combine(end_day, time(0), tzinfo=zone).astimezone(UTC),
    )


def lookup_key(kind: BiasKind, period_date: date, symbol: str) -> tuple[BiasKind, date, str]:
    return kind, period_date, symbol.casefold()


def match_bias_symbol(trade_symbol: str, symbols: Iterable[str]) -> str | None:
    """The bias symbol ``trade_symbol`` starts with (case-insensitive), or None.

    bias.yaml guarantees no symbol is the prefix of another, so at most one matches.
    """
    folded = trade_symbol.casefold()
    return next((s for s in symbols if folded.startswith(s.casefold())), None)


def daily_periods(open_time: datetime, settings: AlignmentSettings) -> tuple[BiasPeriod, ...]:
    """Daily bias candidates of a trade, most specific first."""
    local = to_local(open_time, settings.tz)
    day = local.date()
    if local.time().replace(tzinfo=None) < settings.pre_ny_from:
        return (BiasPeriod(BiasKind.PRE_LONDON, day),)
    return (BiasPeriod(BiasKind.PRE_NY, day), BiasPeriod(BiasKind.PRE_LONDON, day))


def trade_periods(open_time: datetime, settings: AlignmentSettings) -> tuple[BiasPeriod, ...]:
    """Every period whose note can decide one of the trade's three alignments."""
    day = to_local(open_time, settings.tz).date()
    return (
        *daily_periods(open_time, settings),
        BiasPeriod(BiasKind.WEEKLY, week_start(day)),
        BiasPeriod(BiasKind.MONTHLY, month_start(day)),
    )


def alignment(trade_direction: str, bias_direction: str | None) -> BiasAlignment:
    """Trade direction (buy/sell) against a bias direction (None = no entry)."""
    if bias_direction is None:
        return BiasAlignment.NO_BIAS
    bias = BiasDirection(bias_direction)
    if bias is BiasDirection.NEUTRAL:
        return BiasAlignment.NEUTRAL_BIAS
    if bias is BiasDirection.NO_TRADE:
        return BiasAlignment.COUNTER
    expected = Direction.BUY if bias is BiasDirection.BULLISH else Direction.SELL
    if Direction(trade_direction) is expected:
        return BiasAlignment.ALIGNED
    return BiasAlignment.COUNTER


def _first_entry(periods: Sequence[BiasPeriod], symbol: str, lookup: BiasLookup) -> BiasRef | None:
    for period in periods:
        ref = lookup.get(lookup_key(period.kind, period.period_date, symbol))
        if ref is not None:
            return ref
    return None


def align_trade(
    symbol: str,
    direction: str,
    open_time: datetime,
    settings: AlignmentSettings,
    lookup: BiasLookup,
) -> TradeBias:
    """Daily, weekly and monthly alignment of one trade (see module doc)."""
    bias_symbol = match_bias_symbol(symbol, settings.symbols)
    if bias_symbol is None:
        return NO_BIAS
    periods = trade_periods(open_time, settings)
    daily = _first_entry(periods[:-2], bias_symbol, lookup)
    weekly = _first_entry(periods[-2:-1], bias_symbol, lookup)
    monthly = _first_entry(periods[-1:], bias_symbol, lookup)
    return TradeBias(
        daily=alignment(direction, daily.direction if daily else None),
        weekly=alignment(direction, weekly.direction if weekly else None),
        monthly=alignment(direction, monthly.direction if monthly else None),
        daily_note_id=daily.note_id if daily else None,
        weekly_note_id=weekly.note_id if weekly else None,
        monthly_note_id=monthly.note_id if monthly else None,
    )

"""Bias alignment rules (PRD 6.6; DECISIONS 2026-11-05 M4, M4-04)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from app.domain.bias_alignment import (
    NO_BIAS,
    AlignmentSettings,
    BiasPeriod,
    BiasRef,
    align_trade,
    alignment,
    daily_periods,
    lookup_key,
    match_bias_symbol,
    month_start,
    normalize_period,
    period_utc_range,
    trade_periods,
    week_start,
)
from app.models.enums import BiasAlignment, BiasKind

SETTINGS = AlignmentSettings(
    symbols=("EURUSD", "GBPUSD", "XAUUSD", "GER40"), tz="Europe/Brussels", pre_ny_from=time(11)
)
TUE = date(2026, 11, 3)  # winter time, UTC+1


def utc(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


# --- mapping ---


@pytest.mark.parametrize(
    ("trade", "bias", "expected"),
    [
        ("buy", "bullish", BiasAlignment.ALIGNED),
        ("sell", "bearish", BiasAlignment.ALIGNED),
        ("buy", "bearish", BiasAlignment.COUNTER),
        ("sell", "bullish", BiasAlignment.COUNTER),
        ("buy", "neutral", BiasAlignment.NEUTRAL_BIAS),
        ("sell", "neutral", BiasAlignment.NEUTRAL_BIAS),
        ("buy", "no_trade", BiasAlignment.COUNTER),
        ("sell", "no_trade", BiasAlignment.COUNTER),
        ("buy", None, BiasAlignment.NO_BIAS),
        ("sell", None, BiasAlignment.NO_BIAS),
    ],
)
def test_alignment_mapping(trade: str, bias: str | None, expected: BiasAlignment) -> None:
    assert alignment(trade, bias) is expected


# --- periods ---


@pytest.mark.parametrize(
    ("before", "at"),
    [
        (utc(2026, 11, 3, 9, 59, 59), utc(2026, 11, 3, 10, 0)),  # winter, CET
        (utc(2026, 7, 7, 8, 59, 59), utc(2026, 7, 7, 9, 0)),  # summer, CEST
    ],
)
def test_pre_ny_boundary_is_local_11(before: datetime, at: datetime) -> None:
    day = before.date()
    assert daily_periods(before, SETTINGS) == (BiasPeriod(BiasKind.PRE_LONDON, day),)
    assert daily_periods(at, SETTINGS) == (
        BiasPeriod(BiasKind.PRE_NY, day),
        BiasPeriod(BiasKind.PRE_LONDON, day),
    )


def test_boundary_follows_settings() -> None:
    settings = AlignmentSettings(SETTINGS.symbols, SETTINGS.tz, time(11, 30))
    assert daily_periods(utc(2026, 11, 3, 10, 15), settings)[0].kind is BiasKind.PRE_LONDON


def test_local_date_not_utc_date() -> None:
    # 23:30 UTC Monday = 00:30 Tuesday Brussels.
    assert daily_periods(utc(2026, 11, 2, 23, 30), SETTINGS) == (
        BiasPeriod(BiasKind.PRE_LONDON, TUE),
    )


def test_week_and_month_across_month_boundary() -> None:
    # Sunday 1 Nov 2026 belongs to the week of Monday 26 Oct, month November.
    periods = trade_periods(utc(2026, 11, 1, 12, 0), SETTINGS)
    assert periods[-2:] == (
        BiasPeriod(BiasKind.WEEKLY, date(2026, 10, 26)),
        BiasPeriod(BiasKind.MONTHLY, date(2026, 11, 1)),
    )


@pytest.mark.parametrize(
    ("day", "monday"),
    [
        (date(2026, 11, 2), date(2026, 11, 2)),
        (date(2026, 11, 8), date(2026, 11, 2)),  # Sunday
        (date(2026, 10, 1), date(2026, 9, 28)),
    ],
)
def test_week_start(day: date, monday: date) -> None:
    assert week_start(day) == monday


def test_normalize_period() -> None:
    assert normalize_period(BiasKind.WEEKLY, date(2026, 11, 6)) == date(2026, 11, 2)
    assert normalize_period(BiasKind.MONTHLY, date(2026, 11, 6)) == date(2026, 11, 1)
    assert normalize_period(BiasKind.PRE_NY, date(2026, 11, 7)) == date(2026, 11, 7)
    assert month_start(date(2026, 12, 31)) == date(2026, 12, 1)


def test_period_utc_range() -> None:
    assert period_utc_range(BiasKind.PRE_LONDON, TUE, "Europe/Brussels") == (
        utc(2026, 11, 2, 23, 0),
        utc(2026, 11, 3, 23, 0),
    )
    # Week of the DST switch (Sun 25 Oct 2026): starts CEST, ends CET.
    assert period_utc_range(BiasKind.WEEKLY, date(2026, 10, 21), "Europe/Brussels") == (
        utc(2026, 10, 18, 22, 0),
        utc(2026, 10, 25, 23, 0),
    )
    assert period_utc_range(BiasKind.MONTHLY, date(2026, 12, 15), "Europe/Brussels") == (
        utc(2026, 11, 30, 23, 0),
        utc(2026, 12, 31, 23, 0),
    )


# --- symbols ---


@pytest.mark.parametrize(
    ("trade_symbol", "expected"),
    [
        ("GER40", "GER40"),
        ("GER40.cash", "GER40"),
        ("XAUUSD+", "XAUUSD"),
        ("xauusd.r", "XAUUSD"),
        ("EURUSDm", "EURUSD"),
        ("US30", None),
        ("GER", None),  # shorter than the bias symbol
    ],
)
def test_prefix_matching(trade_symbol: str, expected: str | None) -> None:
    assert match_bias_symbol(trade_symbol, SETTINGS.symbols) == expected


# --- whole trade ---


def lookup(*items: tuple[BiasKind, date, str, str]) -> dict[tuple[BiasKind, date, str], BiasRef]:
    return {
        lookup_key(kind, day, symbol): BiasRef(note_id=n, direction=direction)
        for n, (kind, day, symbol, direction) in enumerate(items, start=1)
    }


FULL = lookup(
    (BiasKind.PRE_LONDON, TUE, "XAUUSD", "bullish"),
    (BiasKind.PRE_NY, TUE, "XAUUSD", "bearish"),
    (BiasKind.WEEKLY, date(2026, 11, 2), "XAUUSD", "neutral"),
    (BiasKind.MONTHLY, date(2026, 11, 1), "XAUUSD", "no_trade"),
)


def test_align_trade_london() -> None:
    result = align_trade("XAUUSD.r", "buy", utc(2026, 11, 3, 8, 30), SETTINGS, FULL)
    assert (result.daily, result.weekly, result.monthly) == (
        BiasAlignment.ALIGNED,
        BiasAlignment.NEUTRAL_BIAS,
        BiasAlignment.COUNTER,
    )
    assert (result.daily_note_id, result.weekly_note_id, result.monthly_note_id) == (1, 3, 4)


def test_align_trade_ny_uses_pre_ny() -> None:
    result = align_trade("XAUUSD", "buy", utc(2026, 11, 3, 13, 30), SETTINGS, FULL)
    assert result.daily is BiasAlignment.COUNTER
    assert result.daily_note_id == 2


def test_pre_ny_falls_back_to_pre_london() -> None:
    data = lookup(
        (BiasKind.PRE_LONDON, TUE, "XAUUSD", "bearish"),
        (BiasKind.PRE_NY, TUE, "GER40", "bullish"),  # pre-NY note without XAUUSD
    )
    result = align_trade("XAUUSD", "sell", utc(2026, 11, 3, 14, 0), SETTINGS, data)
    assert result.daily is BiasAlignment.ALIGNED
    assert result.daily_note_id == 1


def test_london_trade_never_uses_pre_ny() -> None:
    data = lookup((BiasKind.PRE_NY, TUE, "XAUUSD", "bullish"))
    result = align_trade("XAUUSD", "buy", utc(2026, 11, 3, 9, 0), SETTINGS, data)
    assert result.daily is BiasAlignment.NO_BIAS
    assert result.daily_note_id is None


def test_other_day_or_symbol_is_no_bias() -> None:
    result = align_trade("GER40", "buy", utc(2026, 11, 4, 9, 0), SETTINGS, FULL)
    assert result == NO_BIAS


def test_unknown_symbol_is_no_bias_everywhere() -> None:
    data = lookup((BiasKind.MONTHLY, date(2026, 11, 1), "US30", "bullish"))
    assert align_trade("US30", "buy", utc(2026, 11, 3, 9, 0), SETTINGS, data) == NO_BIAS


def test_sunday_trade_uses_previous_monday() -> None:
    data = lookup((BiasKind.WEEKLY, date(2026, 11, 2), "EURUSD", "bearish"))
    result = align_trade("EURUSD", "sell", utc(2026, 11, 8, 20, 0), SETTINGS, data)
    assert result.weekly is BiasAlignment.ALIGNED

"""M6-04 (RED): digest metrics extensions, docs/api.md "M6 - Dashboard and digests".

Module extended: ``app/domain/digest_metrics.py`` (pure). New / changed public API:

- ``DigestTrade`` loses ``entry_model``, ``poi_type``, ``followed_plan``, ``emotion_before`` and
  gains ``journal: Mapping[str, str | int | bool | None] = {}`` (journal field key -> value, a
  column field and an ``extra`` field alike; a missing key and None both mean "not filled"),
  plus ``bias_alignment_weekly`` / ``bias_alignment_monthly`` (str | None, auto values).
  ``bias_alignment`` stays the EFFECTIVE daily value (override ?? auto).
- ``TRADE_BREAKDOWN_FIELDS`` = (symbol, session, hour, weekday, bias_alignment) replaces
  ``BREAKDOWN_FIELDS``.
- ``breakdown(trades, field, *, journal=False)``: ``journal=True`` reads ``trade.journal[field]``
  (any key, no ValueError), otherwise ``field`` must be in TRADE_BREAKDOWN_FIELDS (ValueError).
- ``breakdowns(trades, journal_fields=())``: read-only mapping, trade fields first, then the given
  journal field keys in the given order; a journal key that is also a trade field is skipped
  (``bias_alignment`` is both: the trade field wins).
- ``BIAS_SCOPES`` = ("daily", "weekly", "monthly"); ``bias_section(trades, was_correct,
  scope="daily")`` takes the alignment from ``bias_alignment`` / ``bias_alignment_weekly`` /
  ``bias_alignment_monthly``; ``bias_sections(trades, marks)`` with ``marks`` a mapping scope ->
  was_correct values returns a read-only mapping with all three scopes (a missing scope = no
  entries).
- ``NORM_MIN_TRADING_DAYS`` = 20; ``trading_days_of_history(trades, start) -> int`` = weekdays
  (Mon-Fri) from the Brussels date of the first trade (inclusive) to ``start`` (exclusive), 0
  without trades; ``norm_available(trades, start) -> bool`` = that count >= 20.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.domain.digest_metrics import (
    BIAS_SCOPES,
    NORM_MIN_TRADING_DAYS,
    TRADE_BREAKDOWN_FIELDS,
    DigestTrade,
    bias_section,
    bias_sections,
    breakdown,
    breakdowns,
    norm_available,
    trading_days_of_history,
)

D = Decimal


def tr(tid: int, pnl: str, r: str | None, close: datetime, **kw: Any) -> DigestTrade:
    return DigestTrade(
        id=tid,
        account_id=1,
        symbol="XAUUSD",
        close_time=close,
        net_pnl=D(pnl),
        r_multiple=None if r is None else D(r),
        **kw,
    )


def utc(m: int, d: int, h: int = 9, y: int = 2026) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


# --- journal-driven breakdowns ---------------------------------------------------------------


def journal_trades() -> list[DigestTrade]:
    return [
        tr(1, "100", "1", utc(3, 2), journal={"entry_model": "ob", "my_extra": "x", "plan": True}),
        tr(
            2, "-50", "-1", utc(3, 3), journal={"entry_model": "ob", "my_extra": "y", "plan": False}
        ),
        tr(3, "30", "0.5", utc(3, 4), journal={"entry_model": "fvg", "plan": None}),
        tr(4, "10", None, utc(3, 5)),  # nothing filled
    ]


def test_journal_breakdown_reads_the_generic_mapping_with_a_none_group_and_coverage() -> None:
    b = breakdown(journal_trades(), "entry_model", journal=True)

    assert [g.key for g in b.groups] == ["fvg", "ob", None]
    fvg, ob, empty = b.groups
    assert (fvg.trades, fvg.net_pnl, fvg.total_r) == (1, D("30"), D("0.5"))
    assert (ob.trades, ob.net_pnl, ob.total_r, ob.win_rate) == (2, D("50"), D("0"), D("50"))
    assert (empty.trades, empty.net_pnl) == (1, D("10"))
    assert (b.filled, b.total) == (3, 4)


def test_extra_field_with_a_missing_key_counts_as_not_filled() -> None:
    b = breakdown(journal_trades(), "my_extra", journal=True)

    assert [g.key for g in b.groups] == ["x", "y", None]
    assert (b.filled, b.total) == (2, 4)  # t3 and t4 have no such key


def test_boolean_journal_values_group_false_before_true_and_false_is_filled() -> None:
    b = breakdown(journal_trades(), "plan", journal=True)

    assert [g.key for g in b.groups] == [False, True, None]
    assert (b.filled, b.total) == (2, 4)


def test_journal_flag_off_still_rejects_non_trade_fields() -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        breakdown(journal_trades(), "entry_model")


def test_trade_breakdown_fields_are_the_fixed_five() -> None:
    assert TRADE_BREAKDOWN_FIELDS == ("symbol", "session", "hour", "weekday", "bias_alignment")


def test_breakdowns_puts_trade_fields_first_then_journal_fields_in_order() -> None:
    result = breakdowns(journal_trades(), ("plan", "entry_model", "my_extra"))

    assert tuple(result) == (*TRADE_BREAKDOWN_FIELDS, "plan", "entry_model", "my_extra")
    assert result["entry_model"].total == 4
    assert result["my_extra"].filled == 2


def test_breakdowns_skips_a_journal_key_that_is_also_a_trade_field() -> None:
    result = breakdowns(journal_trades(), ("bias_alignment", "entry_model"))

    assert tuple(result) == (*TRADE_BREAKDOWN_FIELDS, "entry_model")


def test_breakdowns_without_journal_fields_has_only_trade_fields_and_is_read_only() -> None:
    result = breakdowns(journal_trades())

    assert tuple(result) == TRADE_BREAKDOWN_FIELDS
    with pytest.raises(TypeError):
        result["x"] = result["symbol"]  # type: ignore[index]


def test_journal_mapping_defaults_to_empty() -> None:
    assert DigestTrade(1, 1, "X", utc(3, 2), D("1"), None).journal == {}


# --- bias per scope --------------------------------------------------------------------------


def bias_trades() -> list[DigestTrade]:
    return [
        tr(
            1,
            "200",
            "2",
            utc(3, 2),
            bias_alignment="aligned",
            bias_alignment_weekly="aligned",
            bias_alignment_monthly="counter",
        ),
        tr(
            2,
            "-100",
            "-1",
            utc(3, 3),
            bias_alignment="counter",
            bias_alignment_weekly="aligned",
            bias_alignment_monthly="counter",
        ),
        tr(3, "300", "3", utc(3, 4), bias_alignment="aligned", bias_alignment_weekly="counter"),
        tr(4, "7", None, utc(3, 5), bias_alignment="no_bias"),
    ]


def test_bias_scopes_constant() -> None:
    assert BIAS_SCOPES == ("daily", "weekly", "monthly")


def test_daily_scope_is_the_default_and_uses_the_effective_alignment() -> None:
    s = bias_section(bias_trades(), [])

    assert (s.aligned.trades, s.aligned.net_pnl, s.aligned.total_r) == (2, D("500"), D("5"))
    assert (s.counter.trades, s.counter.net_pnl, s.counter.total_r) == (1, D("-100"), D("-1"))


def test_weekly_scope_uses_the_weekly_alignment() -> None:
    s = bias_section(bias_trades(), [], scope="weekly")

    assert (s.aligned.trades, s.aligned.net_pnl, s.aligned.total_r) == (2, D("100"), D("1"))
    assert (s.counter.trades, s.counter.net_pnl, s.counter.total_r) == (1, D("300"), D("3"))


def test_monthly_scope_uses_the_monthly_alignment() -> None:
    s = bias_section(bias_trades(), [], scope="monthly")

    assert (s.aligned.trades, s.aligned.net_pnl) == (0, D("0"))
    assert (s.counter.trades, s.counter.net_pnl, s.counter.total_r) == (2, D("100"), D("1"))


def test_unknown_bias_scope_is_rejected() -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        bias_section([], [], scope="yearly")


def test_bias_sections_returns_all_three_scopes_with_their_own_accuracy() -> None:
    result = bias_sections(
        bias_trades(),
        {"daily": [True, False, None], "weekly": [True], "monthly": [False, False]},
    )

    assert tuple(result) == BIAS_SCOPES
    daily = result["daily"]
    assert (daily.accuracy, daily.marked, daily.total) == (D("50"), 2, 3)
    assert (result["weekly"].accuracy, result["weekly"].marked) == (D("100"), 1)
    assert (result["monthly"].accuracy, result["monthly"].total) == (D("0"), 2)
    assert result["weekly"].aligned.trades == 2  # alignment follows the scope
    assert result["monthly"].aligned.trades == 0


def test_bias_sections_missing_scope_means_no_entries() -> None:
    result = bias_sections(bias_trades(), {"daily": [True]})

    weekly = result["weekly"]
    assert (weekly.accuracy, weekly.marked, weekly.total) == (None, 0, 0)
    with pytest.raises(TypeError):
        result["daily"] = weekly  # type: ignore[index]


# --- norm availability -----------------------------------------------------------------------

START = date(2026, 3, 2)  # Monday


def first_trade_at(close: datetime) -> list[DigestTrade]:
    return [tr(1, "1", "1", close)]


def test_minimum_is_twenty_trading_days() -> None:
    assert NORM_MIN_TRADING_DAYS == 20


def test_exactly_twenty_weekdays_of_history_is_available() -> None:
    trades = first_trade_at(utc(2, 2, 10))  # Mon Feb 2 .. Fri Feb 27 = 4 weeks = 20 weekdays

    assert trading_days_of_history(trades, START) == 20
    assert norm_available(trades, START) is True


def test_nineteen_weekdays_of_history_is_not_available() -> None:
    trades = first_trade_at(utc(2, 3, 10))

    assert trading_days_of_history(trades, START) == 19
    assert norm_available(trades, START) is False


def test_a_weekend_first_trade_counts_from_the_next_monday() -> None:
    assert trading_days_of_history(first_trade_at(utc(1, 31, 10)), START) == 20  # Sat Jan 31
    assert trading_days_of_history(first_trade_at(utc(2, 1, 10)), START) == 20  # Sun Feb 1


def test_history_counts_from_the_first_trade_even_when_later_trades_exist() -> None:
    trades = [*first_trade_at(utc(2, 2, 10)), tr(2, "1", "1", utc(2, 20))]

    assert norm_available(trades, START) is True


def test_first_trade_uses_the_brussels_date() -> None:
    # Sun Feb 1 23:30 UTC is Mon Feb 2 00:30 in Brussels -> 20 weekdays.
    late_sunday = datetime(2026, 2, 1, 23, 30, tzinfo=UTC)
    # Mon Feb 2 23:30 UTC is Tue Feb 3 00:30 in Brussels -> 19 weekdays.
    late_monday = datetime(2026, 2, 2, 23, 30, tzinfo=UTC)

    assert trading_days_of_history(first_trade_at(late_sunday), START) == 20
    assert trading_days_of_history(first_trade_at(late_monday), START) == 19


def test_no_trades_or_first_trade_at_or_after_the_period_is_not_available() -> None:
    assert trading_days_of_history([], START) == 0
    assert norm_available([], START) is False
    assert trading_days_of_history(first_trade_at(utc(3, 2, 10)), START) == 0
    assert norm_available(first_trade_at(utc(3, 4, 10)), START) is False

"""M6-03 shared period P&L (extracted from ``rules._period_stop``) and limit state.

API under test, module ``app.domain.period_pnl`` (pure, no DB):

- ``local_day(dt, tz) -> date`` and ``week_start(dt, tz) -> date`` (Monday): the period keys,
  evaluated in the config timezone (Europe/Brussels); ``dt`` is aware UTC.
- ``PeriodExtremes`` frozen dataclass ``(pnl, pct, low_pnl, low_pct, high_pnl, high_pct)``:
  ``pnl``/``pct`` = current running total, low/high = sticky extremes of the running total
  (both start at 0, so low <= 0 <= high). ``pct`` values are % of the account size.
- ``period_extremes(closed_trades, period_key_fn, start_key, size, before=None)``:
  ``closed_trades`` = iterable of objects with ``key``, ``close_time`` (aware UTC or None),
  ``net_pnl`` (Decimal or None). Counted: close_time and net_pnl set,
  ``period_key_fn(close_time) == start_key`` and (``before`` is None or ``close_time < before``).
  Replayed in (close_time, key) order. Returns ``None`` when ``size`` is None, not finite or <= 0.
- ``limit_state(extremes, loss_pct, profit_pct) -> "ok" | "stop_loss" | "stop_profit"``:
  ``low_pct <= loss_pct`` -> stop_loss (wins over profit); ``high_pct >= profit_pct`` ->
  stop_profit; a limit of ``None`` (rule disabled) or ``extremes is None`` never stops.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import NamedTuple

import pytest

from app.domain.period_pnl import (
    PeriodExtremes,
    limit_state,
    local_day,
    period_extremes,
    week_start,
)

D = Decimal
TZ = "Europe/Brussels"
SIZE = D("10000")


class Closed(NamedTuple):
    key: int
    close_time: datetime | None
    net_pnl: Decimal | None


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def day_key(dt: datetime) -> date:
    return local_day(dt, TZ)


def week_key(dt: datetime) -> date:
    return week_start(dt, TZ)


def run(
    trades: list[Closed],
    key_fn: Callable[[datetime], date],
    start: date,
    size: Decimal | None = SIZE,
    before: datetime | None = None,
) -> PeriodExtremes | None:
    return period_extremes(trades, key_fn, start, size, before)


# --- period keys -----------------------------------------------------------------------------


def test_local_day_and_week_start_use_brussels_time() -> None:
    sunday_late = utc(2026, 11, 8, 22, 30)  # Sun 23:30 Brussels (UTC+1)
    monday_early = utc(2026, 11, 8, 23, 30)  # Mon 00:30 Brussels

    assert local_day(sunday_late, TZ) == date(2026, 11, 8)
    assert week_start(sunday_late, TZ) == date(2026, 11, 2)
    assert local_day(monday_early, TZ) == date(2026, 11, 9)
    assert week_start(monday_early, TZ) == date(2026, 11, 9)


# --- period_extremes -------------------------------------------------------------------------


def test_sticky_low_stays_after_recovery() -> None:
    trades = [
        Closed(1, utc(2026, 11, 12, 9), D("-320")),
        Closed(2, utc(2026, 11, 12, 10), D("150")),
    ]

    ex = run(trades, day_key, date(2026, 11, 12))

    assert ex == PeriodExtremes(
        pnl=D("-170"),
        pct=D("-1.7"),
        low_pnl=D("-320"),
        low_pct=D("-3.2"),
        high_pnl=D("0"),
        high_pct=D("0"),
    )


def test_high_is_the_peak_of_the_running_total() -> None:
    trades = [
        Closed(1, utc(2026, 11, 12, 9), D("400")),
        Closed(2, utc(2026, 11, 12, 10), D("200")),
        Closed(3, utc(2026, 11, 12, 11), D("-250")),
    ]

    ex = run(trades, day_key, date(2026, 11, 12))

    assert ex is not None
    assert (ex.pnl, ex.high_pnl, ex.high_pct, ex.low_pnl) == (D("350"), D("600"), D("6"), D("0"))


def test_replay_is_in_close_order_then_key_not_input_order() -> None:
    later_loss = Closed(2, utc(2026, 11, 12, 10), D("-100"))
    earlier_win = Closed(1, utc(2026, 11, 12, 9), D("100"))

    ex = run([later_loss, earlier_win], day_key, date(2026, 11, 12))

    assert ex is not None
    assert ex.low_pnl == D("0")  # win first: the running total never goes below 0
    assert ex.high_pnl == D("100")


def test_same_close_time_is_ordered_by_key() -> None:
    t = utc(2026, 11, 12, 9)
    ex = run([Closed(2, t, D("-100")), Closed(1, t, D("100"))], day_key, date(2026, 11, 12))

    assert ex is not None
    assert (ex.low_pnl, ex.high_pnl) == (D("0"), D("100"))


def test_empty_gives_zeros() -> None:
    ex = run([], day_key, date(2026, 11, 12))

    assert ex == PeriodExtremes(D(0), D(0), D(0), D(0), D(0), D(0))


@pytest.mark.parametrize("size", [None, D("0"), D("-1"), D("NaN"), D("Infinity")])
def test_unusable_size_gives_none(size: Decimal | None) -> None:
    trades = [Closed(1, utc(2026, 11, 12, 9), D("-320"))]

    assert run(trades, day_key, date(2026, 11, 12), size) is None


def test_trades_without_close_time_or_pnl_are_ignored() -> None:
    trades = [
        Closed(1, None, D("-500")),
        Closed(2, utc(2026, 11, 12, 9), None),
        Closed(3, utc(2026, 11, 12, 10), D("50")),
    ]

    ex = run(trades, day_key, date(2026, 11, 12))

    assert ex is not None
    assert ex.pnl == D("50")


def test_before_excludes_trades_closed_at_or_after_it() -> None:
    trades = [
        Closed(1, utc(2026, 11, 12, 9), D("-100")),
        Closed(2, utc(2026, 11, 12, 10), D("-200")),
        Closed(3, utc(2026, 11, 12, 11), D("-300")),
    ]

    ex = run(trades, day_key, date(2026, 11, 12), before=utc(2026, 11, 12, 10))

    assert ex is not None
    assert ex.pnl == D("-100")  # the trade closed exactly at `before` is not counted


def test_day_boundary_brussels_midnight() -> None:
    trades = [
        Closed(1, utc(2026, 11, 11, 22, 59), D("-10")),  # 23:59 Brussels, previous day
        Closed(2, utc(2026, 11, 11, 23, 0), D("-20")),  # 00:00 Brussels, the day
        Closed(3, utc(2026, 11, 12, 22, 59), D("-40")),  # 23:59 Brussels, the day
        Closed(4, utc(2026, 11, 12, 23, 0), D("-80")),  # next day
    ]

    ex = run(trades, day_key, date(2026, 11, 12))

    assert ex is not None
    assert ex.pnl == D("-60")


def test_week_boundary_sunday_2330_belongs_to_the_old_week() -> None:
    trades = [
        Closed(1, utc(2026, 11, 8, 22, 30), D("-100")),  # Sun 23:30 Brussels
        Closed(2, utc(2026, 11, 8, 23, 30), D("30")),  # Mon 00:30 Brussels
    ]

    this_week = run(trades, week_key, date(2026, 11, 9))
    old_week = run(trades, week_key, date(2026, 11, 2))

    assert this_week is not None
    assert old_week is not None
    assert this_week.pnl == D("30")
    assert old_week.pnl == D("-100")


def test_dst_end_day_is_25_hours_long() -> None:
    # 2026-10-25: Brussels leaves DST at 03:00 CEST -> 02:00 CET (UTC+2 -> UTC+1).
    trades = [
        Closed(1, utc(2026, 10, 24, 21, 30), D("1")),  # 23:30 CEST on the 24th
        Closed(2, utc(2026, 10, 24, 22, 30), D("10")),  # 00:30 CEST on the 25th
        Closed(3, utc(2026, 10, 25, 22, 30), D("100")),  # 23:30 CET on the 25th
        Closed(4, utc(2026, 10, 25, 23, 30), D("1000")),  # 00:30 CET on the 26th
    ]

    ex = run(trades, day_key, date(2026, 10, 25))

    assert ex is not None
    assert ex.pnl == D("110")


def test_dst_week_runs_monday_to_sunday_local() -> None:
    trades = [
        Closed(1, utc(2026, 10, 18, 21, 59), D("1")),  # Sun 23:59 CEST, week of the 12th
        Closed(2, utc(2026, 10, 18, 22, 0), D("10")),  # Mon 00:00 CEST, week of the 19th
        Closed(3, utc(2026, 10, 25, 22, 59), D("100")),  # Sun 23:59 CET, week of the 19th
        Closed(4, utc(2026, 10, 25, 23, 0), D("1000")),  # Mon 00:00 CET, week of the 26th
    ]

    ex = run(trades, week_key, date(2026, 10, 19))

    assert ex is not None
    assert ex.pnl == D("110")


# --- limit_state -----------------------------------------------------------------------------


def extremes(low_pct: str = "0", high_pct: str = "0") -> PeriodExtremes:
    low, high = D(low_pct), D(high_pct)
    return PeriodExtremes(D(0), D(0), low * 100, low, high * 100, high)


def state(low: str = "0", high: str = "0") -> str:
    return limit_state(extremes(low, high), D("-3"), D("5"))


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        ("0", "0", "ok"),
        ("-2.99", "4.99", "ok"),
        ("-3.0", "0", "stop_loss"),
        ("-3.01", "0", "stop_loss"),
        ("0", "5.0", "stop_profit"),
        ("0", "5.01", "stop_profit"),
        ("-3.0", "5.0", "stop_loss"),  # loss wins
        ("-10", "10", "stop_loss"),
    ],
)
def test_limit_state_boundaries(low: str, high: str, expected: str) -> None:
    assert state(low, high) == expected


def test_limit_state_uses_the_sticky_extreme_not_the_current_total() -> None:
    recovered = PeriodExtremes(D(-170), D("-1.7"), D(-320), D("-3.2"), D(0), D(0))

    assert limit_state(recovered, D("-3"), D("5")) == "stop_loss"


def test_limit_state_without_extremes_is_ok() -> None:
    assert limit_state(None, D("-3"), D("5")) == "ok"


def test_limit_state_disabled_limits_never_stop() -> None:
    ex = extremes("-50", "50")

    assert limit_state(ex, None, None) == "ok"
    assert limit_state(ex, None, D("5")) == "stop_profit"
    assert limit_state(ex, D("-3"), None) == "stop_loss"

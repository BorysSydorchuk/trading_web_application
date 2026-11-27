"""app.domain.equal_weight: each account counts the same (owner 2026-11-27)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D  # noqa: N817

from app.domain import equal_weight as ew
from app.domain.home_charts import ChartTrade

T0 = datetime(2026, 11, 12, 9, tzinfo=UTC)
SIZES = {1: D("10000"), 2: D("100000")}


def _t(i: int, account: int, pnl: str, r: str | None = None, minutes: int = 0) -> ChartTrade:
    return ChartTrade(
        i, account, T0 + timedelta(minutes=minutes), D(pnl), D(r) if r else None, False
    )


def test_same_percent_on_two_sizes_is_that_percent() -> None:
    trades = [_t(1, 1, "200"), _t(2, 2, "2000", minutes=1)]
    base = ew.basis(SIZES, [1, 2])
    assert ew.cumulative(trades, base) == [D("0"), D("1.0000"), D("2.0000")]
    assert list(ew.by_day(trades, base).values()) == [D("2.0000")]


def test_one_account_is_its_own_percent() -> None:
    trades = [_t(1, 2, "1500")]
    assert ew.cumulative(trades, ew.basis(SIZES, [2]))[-1] == D("1.5000")


def test_missing_size_gives_no_percent() -> None:
    assert ew.basis({1: D("10000"), 2: D("0")}, [1, 2]) is None
    assert ew.basis({1: D("10000")}, [1, 3]) is None
    assert ew.cumulative([_t(1, 1, "5")], None) == [None, None]
    assert ew.by_day([_t(1, 1, "5")], None) == {}


def test_no_counted_account_is_zero() -> None:
    assert ew.cumulative([], ew.basis(SIZES, [])) == [D("0")]


def test_average_of_open_pnl() -> None:
    assert ew.average({1: D("-100"), 2: D("3000")}, SIZES) == D("1.0000")
    assert ew.average({1: None, 2: D("3000")}, SIZES) is None
    assert ew.average({}, SIZES) is None


def test_total_r_is_a_plain_sum() -> None:
    assert ew.total_r([_t(1, 1, "1", "2.0"), _t(2, 2, "1", "-0.5"), _t(3, 1, "1")]) == D("1.5000")
    assert ew.total_r([_t(1, 1, "1")]) is None

"""Tests for MAE / MFE computation (M8-16). Decimal only, realistic FX/gold numbers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.excursion import Excursion, PriceSample, bar, compute_excursion, tick
from app.models.enums import Direction

D = Decimal
T0 = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
EUR_POINT = D("0.00001")
GOLD_POINT = D("0.01")


def at(minutes: int, seconds: int = 0) -> datetime:
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def run(
    direction: Direction,
    entry: str,
    sl: str | None,
    samples: Iterable[PriceSample],
    point: Decimal | None = EUR_POINT,
    end: datetime | None = None,
) -> Excursion | None:
    return compute_excursion(
        direction,
        D(entry),
        None if sl is None else D(sl),
        T0,
        end or at(60),
        samples,
        point,
    )


def test_helpers_build_samples() -> None:
    t = tick(at(1), D("1.08500"), D("1.08512"))
    assert (t.bid_high, t.bid_low) == (D("1.08500"), D("1.08500"))
    assert (t.ask_high, t.ask_low) == (D("1.08512"), D("1.08512"))
    b = bar(at(1), D("1.08600"), D("1.08400"), D("0.00012"))
    assert (b.bid_high, b.bid_low) == (D("1.08600"), D("1.08400"))
    assert (b.ask_high, b.ask_low) == (D("1.08612"), D("1.08412"))
    assert isinstance(t, PriceSample)


def test_long_favourable_then_adverse() -> None:
    samples = [
        tick(at(1), D("1.08490"), D("1.08502")),
        tick(at(5), D("1.08640"), D("1.08652")),
        tick(at(9), D("1.08450"), D("1.08462")),
    ]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mfe_price == D("1.08640")
    assert r.mfe_time == at(5)
    assert r.mfe_distance == D("0.00140")
    assert r.mfe_r == D("1.4000")
    assert r.mfe_points == D("140.0")
    assert r.mae_price == D("1.08450")
    assert r.mae_time == at(9)
    assert r.mae_distance == D("0.00050")
    assert r.mae_r == D("0.5000")
    assert r.mae_points == D("50.0")


def test_short_uses_ask_side() -> None:
    samples = [
        tick(at(2), D("1.08490"), D("1.08510")),
        tick(at(6), D("1.08290"), D("1.08300")),
    ]
    r = run(Direction.SELL, "1.08500", "1.08600", samples)
    assert r is not None
    assert r.mfe_price == D("1.08300")
    assert r.mfe_time == at(6)
    assert r.mfe_distance == D("0.00200")
    assert r.mfe_r == D("2.0000")
    assert r.mae_price == D("1.08510")
    assert r.mae_time == at(2)
    assert r.mae_distance == D("0.00010")
    assert r.mae_r == D("0.1000")


def test_bid_ask_side_gives_different_results() -> None:
    samples = [
        tick(at(3), D("1.08600"), D("1.08615")),
        tick(at(4), D("1.08400"), D("1.08415")),
    ]
    long_r = run(Direction.BUY, "1.08500", "1.08400", samples)
    short_r = run(Direction.SELL, "1.08500", "1.08600", samples)
    assert long_r is not None
    assert short_r is not None
    assert long_r.mfe_price == D("1.08600")
    assert long_r.mae_price == D("1.08400")
    assert short_r.mfe_price == D("1.08415")
    assert short_r.mae_price == D("1.08615")


def test_tp_hit_closing_tick_gives_rr() -> None:
    # Long XAUUSD, SL 10.00, TP 2R = 20.00; closing tick exactly at TP.
    samples = [
        tick(at(10), D("2350.50"), D("2350.80")),
        tick(at(30), D("2370.00"), D("2370.30")),
    ]
    r = run(Direction.BUY, "2350.00", "2340.00", samples, point=GOLD_POINT)
    assert r is not None
    assert r.mfe_r == D("2.0000")
    assert r.mfe_points == D("2000.0")
    assert r.mae_distance == D("0")
    assert r.mae_price == D("2350.00")
    assert r.mae_time == T0


def test_sl_hit_after_favourable_move() -> None:
    samples = [
        tick(at(4), D("1.08580"), D("1.08592")),
        tick(at(20), D("1.08400"), D("1.08412")),
    ]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mfe_r == D("0.8000")
    assert r.mfe_time == at(4)
    assert r.mae_r == D("1.0000")
    assert r.mae_time == at(20)


def test_plain_sl_has_zero_mfe_at_entry() -> None:
    samples = [
        tick(at(1), D("1.08500"), D("1.08512")),
        tick(at(7), D("1.08400"), D("1.08412")),
    ]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mfe_distance == D("0")
    assert r.mfe_r == D("0.0000")
    assert r.mfe_points == D("0.0")
    assert r.mfe_price == D("1.08500")
    assert r.mfe_time == T0
    assert r.mae_r == D("1.0000")


def test_gap_through_sl_mae_above_one() -> None:
    samples = [tick(at(15), D("1.08340"), D("1.08352"))]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mae_distance == D("0.00160")
    assert r.mae_r == D("1.6000")


def test_missing_sl_keeps_distances_and_points() -> None:
    samples = [
        tick(at(2), D("2355.00"), D("2355.30")),
        tick(at(3), D("2347.00"), D("2347.30")),
    ]
    r = run(Direction.BUY, "2350.00", None, samples, point=GOLD_POINT)
    assert r is not None
    assert r.mfe_r is None
    assert r.mae_r is None
    assert r.mfe_distance == D("5.00")
    assert r.mfe_points == D("500.0")
    assert r.mae_distance == D("3.00")
    assert r.mae_points == D("300.0")


def test_sl_equal_entry_gives_no_r() -> None:
    r = run(Direction.BUY, "1.08500", "1.08500", [tick(at(2), D("1.08600"), D("1.08612"))])
    assert r is not None
    assert r.mfe_r is None
    assert r.mae_r is None
    assert r.mfe_distance == D("0.00100")


@pytest.mark.parametrize("point", [None, D("0"), D("-0.00001")])
def test_point_unknown_or_invalid_gives_no_points(point: Decimal | None) -> None:
    r = run(
        Direction.BUY,
        "1.08500",
        "1.08400",
        [tick(at(2), D("1.08600"), D("1.08612"))],
        point=point,
    )
    assert r is not None
    assert r.mfe_points is None
    assert r.mae_points is None
    assert r.mfe_r == D("1.0000")


def test_points_rounded_half_up_one_decimal() -> None:
    # distance 0.0000125 / 0.00001 = 1.25 -> 1.3
    r = run(Direction.BUY, "1.08500", "1.08400", [tick(at(2), D("1.0850125"), D("1.08515"))])
    assert r is not None
    assert r.mfe_points == D("1.3")


def test_r_rounded_half_up_four_decimals() -> None:
    r = run(
        Direction.BUY,
        "100",
        "97",
        [tick(at(1), D("101"), D("101.1")), tick(at(2), D("98"), D("98.1"))],
    )
    assert r is not None
    assert r.mfe_r == D("0.3333")
    assert r.mae_r == D("0.6667")
    # 0.00005 / 1 is an exact half at 4 dp and must round up
    half = run(Direction.BUY, "1", "0", [tick(at(1), D("1.00005"), D("1.1"))])
    assert half is not None
    assert half.mfe_r == D("0.0001")


def test_samples_outside_window_ignored() -> None:
    samples = [
        tick(at(-1), D("1.09000"), D("1.09012")),
        tick(at(5), D("1.08550"), D("1.08562")),
        tick(at(61), D("1.07000"), D("1.07012")),
    ]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mfe_price == D("1.08550")
    assert r.mae_distance == D("0")


def test_window_boundaries_inclusive() -> None:
    samples = [
        tick(T0, D("1.08600"), D("1.08612")),
        tick(at(60), D("1.08300"), D("1.08312")),
    ]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mfe_time == T0
    assert r.mae_time == at(60)


def test_all_samples_outside_window_returns_none() -> None:
    assert run(Direction.BUY, "1.08500", "1.08400", [tick(at(90), D("1.09"), D("1.09"))]) is None


def test_no_samples_returns_none() -> None:
    assert run(Direction.SELL, "1.08500", "1.08600", []) is None


def test_bars_mixed_with_ticks() -> None:
    samples = [
        tick(at(0, 30), D("1.08520"), D("1.08532")),
        bar(at(5), D("1.08700"), D("1.08420"), D("0.00012")),
        tick(at(58), D("1.08460"), D("1.08472")),
    ]
    long_r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert long_r is not None
    assert long_r.mfe_price == D("1.08700")
    assert long_r.mfe_time == at(5)
    assert long_r.mae_price == D("1.08420")
    assert long_r.mae_time == at(5)
    short_r = run(Direction.SELL, "1.08500", "1.08600", samples)
    assert short_r is not None
    assert short_r.mfe_price == D("1.08432")
    assert short_r.mae_price == D("1.08712")


def test_first_time_reaching_extreme_wins_even_if_unordered() -> None:
    samples = [
        tick(at(9), D("1.08600"), D("1.08612")),
        tick(at(3), D("1.08600"), D("1.08612")),
        tick(at(6), D("1.08600"), D("1.08612")),
    ]
    r = run(Direction.BUY, "1.08500", "1.08400", samples)
    assert r is not None
    assert r.mfe_time == at(3)


def test_accepts_one_shot_iterator() -> None:
    r = run(
        Direction.BUY,
        "1.08500",
        "1.08400",
        iter([tick(at(1), D("1.08550"), D("1.08562"))]),
    )
    assert r is not None
    assert r.mfe_r == D("0.5000")


def test_open_equals_end_is_valid() -> None:
    r = run(Direction.BUY, "1.08500", "1.08400", [tick(T0, D("1.08500"), D("1.08512"))], end=T0)
    assert r is not None
    assert r.mfe_distance == D("0")


def test_naive_datetimes_rejected() -> None:
    s = [tick(at(1), D("1.0855"), D("1.0856"))]
    naive = T0.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_excursion(Direction.BUY, D("1.085"), D("1.084"), naive, at(60), s, EUR_POINT)
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_excursion(
            Direction.BUY, D("1.085"), D("1.084"), T0, naive + timedelta(hours=1), s, EUR_POINT
        )


def test_end_before_open_rejected() -> None:
    with pytest.raises(ValueError, match="before open_time"):
        run(Direction.BUY, "1.08500", "1.08400", [], end=at(-1))

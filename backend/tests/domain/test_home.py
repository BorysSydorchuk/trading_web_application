"""M8-10b «Головна» pure math (app.domain.home): drawdown, live R, daily stop room, totals."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import home
from app.domain.home_charts import ChartTrade

D = Decimal
T0 = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
MONTH = date(2026, 11, 1)
SIZE = D("10000")


def trade(i: int, pnl: str, excluded: bool = False) -> ChartTrade:
    return ChartTrade(i, 1, T0 + timedelta(hours=i), D(pnl), None, excluded)


# --- drawdown --------------------------------------------------------------------------------


def test_drawdown_starts_at_zero_at_brussels_month_midnight() -> None:
    points = home.drawdown([], MONTH, SIZE)

    assert points == [home.DrawdownPoint(datetime(2026, 10, 31, 23, 0, tzinfo=UTC), D(0))]


def test_drawdown_is_running_minus_peak_over_size() -> None:
    # running: +200, -100, +300, -200 -> peak 200, 200, 300, 300
    trades = [trade(1, "200"), trade(2, "-300"), trade(3, "400"), trade(4, "-500")]

    pcts = [p.pct for p in home.drawdown(trades, MONTH, SIZE)]

    assert pcts == [D(0), D(0), D(-3), D(0), D(-5)]


def test_drawdown_peak_starts_at_zero_and_includes_excluded_trades() -> None:
    trades = [trade(2, "-50", excluded=True), trade(1, "-100")]  # sorted by close time

    pcts = [p.pct for p in home.drawdown(trades, MONTH, SIZE)]

    assert pcts == [D(0), D("-1"), D("-1.5")]


# --- live R ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "entry", "sl", "price", "expected"),
    [
        ("buy", "100", "90", "105", "0.5"),
        ("buy", "100", "90", "90", "-1"),
        ("sell", "100", "110", "80", "2"),
        ("sell", "100", "110", "105", "-0.5"),
    ],
)
def test_r_now_is_signed_move_over_sl_distance(
    direction: str, entry: str, sl: str, price: str, expected: str
) -> None:
    assert home.r_now(direction, D(entry), D(sl), D(price)) == D(expected)


@pytest.mark.parametrize(
    ("direction", "sl", "price"),
    [
        ("buy", None, "105"),
        ("buy", "100", "105"),
        ("buy", "110", "105"),
        ("sell", "90", "95"),
        ("buy", "90", None),
    ],
)
def test_r_now_is_none_without_a_usable_sl_or_price(
    direction: str, sl: str | None, price: str | None
) -> None:
    sl_value = D(sl) if sl is not None else None
    price_value = D(price) if price is not None else None

    assert home.r_now(direction, D("100"), sl_value, price_value) is None


def test_tp_r_is_tp_distance_over_sl_distance() -> None:
    assert home.tp_r("buy", D("100"), D("90"), D("125")) == D("2.5")
    assert home.tp_r("sell", D("1.163"), D("1.165"), D("1.159")) == D(2)


@pytest.mark.parametrize(("sl", "tp"), [(None, "125"), ("90", None), ("90", "0")])
def test_tp_r_is_none_without_sl_or_tp(sl: str | None, tp: str | None) -> None:
    sl_value = D(sl) if sl is not None else None
    tp_value = D(tp) if tp is not None else None

    assert home.tp_r("buy", D("100"), sl_value, tp_value) is None


# --- daily stop ------------------------------------------------------------------------------


def test_to_daily_stop_is_day_pct_minus_the_stop() -> None:
    assert home.to_daily_stop(D("2.1"), D("-3.0")) == D("5.1")
    assert home.to_daily_stop(D("-2.5"), D("-3.0")) == D("0.5")
    assert home.to_daily_stop(None, D("-3.0")) is None
    assert home.to_daily_stop(D("1"), None) is None


def test_closest_to_daily_stop_picks_the_lowest_room() -> None:
    rooms = {"a": D("5.1"), "b": D("0.4"), "c": None, "d": D("0.4")}

    assert home.closest_to_daily_stop(list(rooms), rooms.get) == "b"  # tie: first


def test_closest_to_daily_stop_without_values_is_the_first_item() -> None:
    assert home.closest_to_daily_stop(["a", "b"], lambda _: None) == "a"
    assert home.closest_to_daily_stop([], lambda _: None) is None


def test_closest_to_daily_stop_handles_zero_room() -> None:
    rooms = {"a": D("1"), "b": D("0"), "c": D("-0.5")}

    assert home.closest_to_daily_stop(list(rooms), rooms.get) == "c"


# --- open totals -----------------------------------------------------------------------------


def test_open_totals_sum_and_oldest_price_time() -> None:
    totals = home.open_totals([D("40"), D("-12.5")], [D("1"), D("0.5")], [T0, T0 - timedelta(1)])

    assert totals == home.OpenTotals(D("27.5"), D("1.5"), T0 - timedelta(1))


def test_open_totals_are_none_when_a_part_is_unknown() -> None:
    totals = home.open_totals([D("40"), None], [D("1"), None], [T0, None])

    assert totals == home.OpenTotals(None, None, None)


def test_open_totals_without_positions_are_zero() -> None:
    assert home.open_totals([], [], []) == home.OpenTotals(D(0), D(0), None)


# --- max loss --------------------------------------------------------------------------------

LIMIT = D("-10.0")


def test_max_loss_floor_is_size_times_one_plus_the_limit() -> None:
    assert home.max_loss_floor(SIZE, LIMIT) == D(9000)


def test_max_loss_distance_is_equity_minus_floor_over_size() -> None:
    assert home.max_loss_distance(D("10056.25"), SIZE, LIMIT) == D("10.5625")
    assert home.max_loss_distance(SIZE, SIZE, LIMIT) == D(10)
    assert home.max_loss_distance(D(9000), SIZE, LIMIT) == D(0)  # failed at the floor


@pytest.mark.parametrize("size", [None, D(0), D(-1), D("NaN")])
def test_usable_size_rejects_missing_or_non_positive(size: Decimal | None) -> None:
    assert home.usable_size(size) is None


def test_max_loss_series_runs_the_balance_from_the_start_to_now() -> None:
    now = T0 + timedelta(days=1)
    closed = [(T0 + timedelta(hours=2), 2, D("-300")), (T0 + timedelta(hours=1), 1, D("100"))]

    points = home.max_loss_series(SIZE, LIMIT, T0, closed, now, D("9850"))

    assert [(p.time, p.pct) for p in points] == [
        (T0, D(10)),
        (T0 + timedelta(hours=1), D(11)),
        (T0 + timedelta(hours=2), D(8)),
        (now, D("8.5")),
    ]


def test_max_loss_series_keeps_the_last_points_and_the_now_point() -> None:
    now = T0 + timedelta(days=30)
    closed = [(T0 + timedelta(hours=i), i, D(1)) for i in range(1, 100)]

    points = home.max_loss_series(SIZE, LIMIT, T0, closed, now, D(0))

    assert len(points) == home.MAX_LOSS_POINTS
    assert points[-1] == home.MaxLossPoint(now, D(-90))
    assert points[-2].time == T0 + timedelta(hours=99)


def test_pick_closest_to_the_floor_uses_the_lowest_pct() -> None:
    items = [("a", D("10.5")), ("b", D("4.2")), ("c", D("4.2"))]

    assert home.closest_to_daily_stop(items, lambda item: item[1]) == ("b", D("4.2"))


D_ = Decimal


@pytest.mark.parametrize(
    ("account_dd", "account_target", "expected"),
    [
        (D_("8.0000"), None, (D_("-8.0000"), None)),  # funded FundedNext: own 8 %, no target
        (D_("8.0000"), D_("4.0000"), (D_("-8.0000"), D_("4.0000"))),
        (None, None, (D_("-10.0"), D_("10.0"))),  # no firm rules on the account -> rules.yaml
        (D_("0"), None, (D_("-10.0"), D_("10.0"))),  # 0 = not set
    ],
)
def test_firm_limits_prefer_the_account_rules_over_the_config_fallback(
    account_dd: Decimal | None, account_target: Decimal | None, expected: tuple[object, object]
) -> None:
    got = home.firm_limits(account_dd, account_target, D_("-10.0"), D_("10.0"))
    assert (got.max_loss_pct, got.profit_target_pct) == expected

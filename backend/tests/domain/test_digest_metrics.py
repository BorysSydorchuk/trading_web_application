"""M6-02 (RED): pure digest metrics, docs/api.md "M6 - Dashboard and digests".

Module to implement: ``app/domain/digest_metrics.py``. No DB, no I/O, Decimal only, every
result type a frozen dataclass, inputs never mutated. Public API (what these tests import):

Input
- ``DigestTrade(id, account_id, symbol, close_time, net_pnl, r_multiple, session=None,
  hour=None, weekday=None, entry_model=None, poi_type=None, bias_alignment=None,
  followed_plan=None, emotion_before=None, violations=())`` frozen. ``close_time`` aware UTC,
  ``net_pnl`` Decimal, ``r_multiple`` Decimal | None, ``bias_alignment`` is the EFFECTIVE value
  ("aligned" | "counter" | other | None), ``hour`` Brussels hour of open, ``weekday`` 0..6,
  ``violations`` tuple of rule keys (a key may repeat within one trade).
- ``account_sizes``: ``Mapping[int, Decimal]`` account_id -> account size.

Periods (Brussels calendar, kind is "weekly" | "monthly", anything else -> ValueError)
- ``brussels_date(dt) -> date``; ``period_start(kind, day) -> date`` (Monday / 1st);
  ``period_end(kind, start) -> date`` (Sunday / last day, inclusive);
  ``trades_in_period(trades, kind, start) -> list[DigestTrade]`` (Brussels close date inside).

Metrics
- ``compute_metrics(trades, account_sizes) -> DigestMetrics`` with fields: trades, wins, losses,
  breakeven, violations (distinct trades with any violation), net_pnl, net_pnl_pct (None when
  there is no trade or a used account has no positive size), total_r, r_n (trades with R),
  win_rate, avg_win_r, avg_loss_r, expectancy_r, profit_factor, max_drawdown (>= 0 money),
  max_drawdown_pct (None like net_pnl_pct), best_trade, worst_trade (DigestTrade | None).
  Ratios are Decimal | None, percents are x100, nothing is rounded (rounding is the API edge).
  Empty: counts 0, net_pnl/total_r/max_drawdown 0, every ratio and trade None.

Breakdowns
- ``BREAKDOWN_FIELDS`` = ("symbol", "session", "hour", "weekday", "entry_model", "poi_type",
  "bias_alignment", "followed_plan", "emotion_before").
- ``breakdown(trades, field) -> Breakdown(field, groups, filled, total)``;
  ``BreakdownGroup(key, trades, net_pnl, total_r, win_rate)``, a None field value is key None,
  groups sorted by key with None last; ``filled`` = trades whose field is not None.
- ``breakdowns(trades) -> dict[str, Breakdown]`` for all BREAKDOWN_FIELDS.

Rules and bias
- ``rule_section(trades) -> RuleSection(rules, violated_trades, violated_pnl)``;
  ``RuleLine(rule_key, violations, trades, pnl)`` sorted by rule_key: violations = occurrences,
  trades/pnl = distinct trades that have the key (pnl signed sum of net_pnl).
- ``bias_section(trades, was_correct) -> BiasSection(accuracy, marked, total, aligned, counter)``;
  ``was_correct`` = per bias entry True / False / None (not marked); accuracy = True/marked*100;
  ``SideStats(trades, net_pnl, total_r)`` over effective alignment "aligned" / "counter".

Norm and deviation
- ``HIGHER_IS_BETTER``, ``LOWER_IS_BETTER`` frozensets of metric names (exactly the contract
  lists, see test); "trades" is in neither. ``PeriodKind = Literal["weekly", "monthly"]``.
- ``EquityCurves.by_account`` and the result of ``breakdowns()`` are read-only mappings
  (item assignment raises TypeError, e.g. ``types.MappingProxyType``).
- ``norm_deviation(metric, value, history, k=Decimal(1)) -> NormResult(value, norm_mean,
  norm_sd, deviation)``; history = per-period values; population SD; < 3 history values ->
  mean/sd None, deviation None; SD 0 or value None -> deviation None; "worse" / "better" only
  strictly beyond k x SD; unknown metric -> ValueError.
- ``metric_series(trades, kind, account_sizes, metric) -> tuple[Decimal, ...]``: metric per
  period that has >= 1 trade (oldest first), None values dropped.
- ``norm_window_start(kind, period_start) -> date`` = ``period_start(kind, <the day 60 weekdays
  before period_start>)`` (aligned to the Monday / 1st of that day, so no partial first period);
  ``norm_window_trades(trades, kind, period_start)`` = trades with Brussels close date in
  [window_start, period_start).

Charts
- ``equity_curves(trades, period_start: date) -> EquityCurves(combined, by_account)``;
  ``EquityPoint(time, cum_pnl)``. Every curve (combined and each account) begins with an origin
  point (Brussels 00:00 of period_start as a UTC instant, cum_pnl 0), then one point per trade in
  (close_time, id) order. No trades -> combined == (origin,) and by_account == {}.
- ``r_distribution(trades) -> tuple[RBucket(lower, upper, count), ...]``: R clamped to [-3, 3],
  bucket lower = floor(r / 0.5) * 0.5, contiguous from min to max bucket, zero buckets kept.
- ``hour_heatmap(trades) -> tuple[HeatCell(weekday, hour, trades, net_pnl), ...]``, non-empty
  cells only, sorted (weekday, hour), trades with weekday or hour None skipped.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.domain.digest_metrics import (
    BREAKDOWN_FIELDS,
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    DigestTrade,
    bias_section,
    breakdown,
    breakdowns,
    brussels_date,
    compute_metrics,
    equity_curves,
    hour_heatmap,
    metric_series,
    norm_deviation,
    norm_window_start,
    norm_window_trades,
    period_end,
    period_start,
    r_distribution,
    rule_section,
    trades_in_period,
)

D = Decimal
SIZES = {1: D("10000"), 2: D("10000")}


def utc(m: int, d: int, h: int, mi: int = 0, y: int = 2026) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def trade(
    tid: int,
    pnl: str,
    r: str | None = None,
    when: datetime | None = None,
    account: int = 1,
    **kw: Any,
) -> DigestTrade:
    return DigestTrade(
        id=tid,
        account_id=account,
        symbol=kw.pop("symbol", "XAUUSD"),
        close_time=when or utc(3, 2, 9),
        net_pnl=D(pnl),
        r_multiple=None if r is None else D(r),
        **kw,
    )


def close(actual: Decimal | None, expected: str, tol: str = "0.0001") -> None:
    assert actual is not None
    assert abs(actual - D(expected)) < D(tol), (actual, expected)


def week() -> list[DigestTrade]:
    """Fixture week Mon 2026-03-02 .. Fri 03-06 (CET, UTC+1), 8 trades on 2 accounts.

    id acct  pnl    R   close(UTC)  symbol  model  bias     violations
    1   1   +200   2.0  Mon 09:00   XAUUSD  OB     aligned  -
    2   1   -100  -1.0  Mon 14:00   XAUUSD  OB     counter  rr_low, risk_high
    3   2   +300   3.0  Tue 10:00   GER30   FVG    aligned  -
    4   2   -100  -1.0  Wed 10:00   GER30   FVG    counter  risk_high
    5   1      0   0.0  Wed 15:00   XAUUSD  -      -        -        (breakeven)
    6   1   +100  none  Thu 10:00   EURUSD  -      -        rr_low   (no R)
    7   2   -200  -2.0  Thu 15:00   GER30   OB     -        risk_high x2
    8   2    +50   1.0  Fri 10:00   EURUSD  -      aligned  -
    """
    return [
        trade(1, "200", "2.0", utc(3, 2, 9), 1, entry_model="OB", bias_alignment="aligned"),
        trade(
            2,
            "-100",
            "-1.0",
            utc(3, 2, 14),
            1,
            entry_model="OB",
            bias_alignment="counter",
            violations=("rr_low", "risk_high"),
        ),
        trade(
            3,
            "300",
            "3.0",
            utc(3, 3, 10),
            2,
            symbol="GER30",
            entry_model="FVG",
            bias_alignment="aligned",
        ),
        trade(
            4,
            "-100",
            "-1.0",
            utc(3, 4, 10),
            2,
            symbol="GER30",
            entry_model="FVG",
            bias_alignment="counter",
            violations=("risk_high",),
        ),
        trade(5, "0", "0.0", utc(3, 4, 15), 1),
        trade(6, "100", None, utc(3, 5, 10), 1, symbol="EURUSD", violations=("rr_low",)),
        trade(
            7,
            "-200",
            "-2.0",
            utc(3, 5, 15),
            2,
            symbol="GER30",
            entry_model="OB",
            violations=("risk_high", "risk_high"),
        ),
        trade(8, "50", "1.0", utc(3, 6, 10), 2, symbol="EURUSD", bias_alignment="aligned"),
    ]


# --- periods (Brussels) ----------------------------------------------------------------------


def test_period_start_and_end_weekly_and_monthly() -> None:
    assert period_start("weekly", date(2026, 3, 8)) == date(2026, 3, 2)  # Sunday -> its Monday
    assert period_start("weekly", date(2026, 3, 2)) == date(2026, 3, 2)
    assert period_end("weekly", date(2026, 3, 2)) == date(2026, 3, 8)
    assert period_start("monthly", date(2026, 3, 17)) == date(2026, 3, 1)
    assert period_end("monthly", date(2026, 3, 1)) == date(2026, 3, 31)
    assert period_end("monthly", date(2028, 2, 1)) == date(2028, 2, 29)  # leap year


def test_unknown_period_kind_is_rejected() -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        period_start("daily", date(2026, 3, 2))  # type: ignore[arg-type]
    with pytest.raises(ValueError):  # noqa: PT011
        trades_in_period([], "yearly", date(2026, 3, 2))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("close_utc", "expected_week"),
    [
        (utc(3, 8, 22, 30), date(2026, 3, 2)),  # Sun 23:30 Brussels (CET) -> same week
        (utc(3, 8, 23, 0), date(2026, 3, 9)),  # Mon 00:00 Brussels -> next week
        (utc(3, 8, 23, 30), date(2026, 3, 9)),  # Mon 00:30 Brussels -> next week
        # DST ends Sun 2026-10-25 03:00 CEST; Sunday evening is already CET (+1).
        (utc(10, 25, 22, 30), date(2026, 10, 19)),  # Sun 23:30 CET -> still that week
        (utc(10, 25, 22, 59), date(2026, 10, 19)),
        (utc(10, 25, 23, 0), date(2026, 10, 26)),  # Mon 00:00 CET
        # DST starts Sun 2026-03-29; Sunday evening is CEST (+2).
        (utc(3, 29, 21, 59), date(2026, 3, 23)),  # Sun 23:59 CEST
        (utc(3, 29, 22, 0), date(2026, 3, 30)),  # Mon 00:00 CEST
    ],
)
def test_week_boundaries_follow_brussels_time_including_dst(
    close_utc: datetime, expected_week: date
) -> None:
    assert period_start("weekly", brussels_date(close_utc)) == expected_week
    in_week = trades_in_period([trade(1, "1", when=close_utc)], "weekly", expected_week)
    assert [t.id for t in in_week] == [1]


@pytest.mark.parametrize(
    ("close_utc", "expected_month"),
    [
        (utc(10, 31, 22, 59), date(2026, 10, 1)),  # Sat 23:59 CET
        (utc(10, 31, 23, 0), date(2026, 11, 1)),  # Sun 00:00 CET
        (utc(3, 31, 21, 59), date(2026, 3, 1)),  # Tue 23:59 CEST
        (utc(3, 31, 22, 0), date(2026, 4, 1)),  # Wed 00:00 CEST
    ],
)
def test_month_boundaries_follow_brussels_time(close_utc: datetime, expected_month: date) -> None:
    assert period_start("monthly", brussels_date(close_utc)) == expected_month


def test_trades_in_period_excludes_other_periods() -> None:
    inside = trade(1, "1", when=utc(3, 4, 10))
    before = trade(2, "1", when=utc(3, 1, 22, 59))  # Sun 23:59 Brussels, previous week
    after = trade(3, "1", when=utc(3, 8, 23, 0))  # Mon 00:00 Brussels, next week
    got = trades_in_period([after, inside, before], "weekly", date(2026, 3, 2))
    assert [t.id for t in got] == [1]


# --- compute_metrics -------------------------------------------------------------------------


def test_week_counts() -> None:
    m = compute_metrics(week(), SIZES)
    # wins: 1,3,6,8 = 4; losses: 2,4,7 = 3; breakeven: 5 = 1
    assert (m.trades, m.wins, m.losses, m.breakeven) == (8, 4, 3, 1)
    assert m.violations == 4  # trades 2, 4, 6, 7 have any violation


def test_week_money_and_percent_use_the_sum_of_account_sizes() -> None:
    m = compute_metrics(week(), SIZES)
    # 200 - 100 + 300 - 100 + 0 + 100 - 200 + 50 = 250; both accounts traded: base 20000
    assert m.net_pnl == D("250")
    assert m.net_pnl_pct == D("1.25")  # 250 / 20000 * 100


def test_week_r_metrics_skip_the_trade_without_r_and_report_n() -> None:
    m = compute_metrics(week(), SIZES)
    # R: 2, -1, 3, -1, 0, -2, 1 (trade 6 has none) -> n = 7, sum = 2
    assert m.r_n == 7
    assert m.total_r == D("2")
    assert m.avg_win_r == D("2")  # wins with R: 2, 3, 1 -> 6 / 3
    close(m.avg_loss_r, "-1.3333")  # -1, -1, -2 -> -4 / 3
    close(m.expectancy_r, "0.2857")  # 2 / 7


def test_week_win_rate_counts_breakeven_as_not_a_win() -> None:
    assert compute_metrics(week(), SIZES).win_rate == D("50")  # 4 / 8 * 100


def test_week_profit_factor() -> None:
    # wins 200 + 300 + 100 + 50 = 650; losses 100 + 100 + 200 = 400
    assert compute_metrics(week(), SIZES).profit_factor == D("1.625")


def test_profit_factor_none_without_a_loss_and_zero_without_a_win() -> None:
    only_wins = [trade(1, "100", "1"), trade(2, "50", "0.5")]
    assert compute_metrics(only_wins, SIZES).profit_factor is None
    only_losses = [trade(1, "-100", "-1")]
    assert compute_metrics(only_losses, SIZES).profit_factor == D("0")


def test_week_max_drawdown_money_and_percent() -> None:
    m = compute_metrics(week(), SIZES)
    # running by (close, id): 200, 100, 400, 300, 300, 400, 200, 250
    # peak 400 -> trough 200 = 200 (earlier fall 400 -> 300 is only 100)
    assert m.max_drawdown == D("200")
    assert m.max_drawdown_pct == D("1")  # 200 / 20000 * 100


def test_max_drawdown_is_zero_when_it_never_falls() -> None:
    m = compute_metrics([trade(1, "100"), trade(2, "0", when=utc(3, 3, 9)), trade(3, "5")], SIZES)
    assert m.max_drawdown == D("0")
    assert m.max_drawdown_pct == D("0")


def test_max_drawdown_counts_a_fall_from_the_zero_start() -> None:
    m = compute_metrics([trade(1, "-100"), trade(2, "30", when=utc(3, 3, 9))], SIZES)
    assert m.max_drawdown == D("100")  # 0 -> -100, then recovers partly
    assert m.max_drawdown_pct == D("1")  # 100 / 10000 * 100


def test_max_drawdown_orders_equal_close_times_by_id() -> None:
    same = utc(3, 2, 9)
    # by id: -50, +100, -30 -> running -50, 50, 20: max drawdown 50 (80 if id 2 came first).
    a = trade(1, "-50", when=same)
    b = trade(2, "100", when=same)
    c = trade(3, "-30", when=same)
    assert compute_metrics([c, b, a], SIZES).max_drawdown == D("50")


def test_best_and_worst_trade() -> None:
    m = compute_metrics(week(), SIZES)
    assert m.best_trade is not None and m.best_trade.id == 3  # +300  # noqa: PT018
    assert m.worst_trade is not None and m.worst_trade.id == 7  # -200  # noqa: PT018


def test_best_and_worst_ties_go_to_the_earlier_close() -> None:
    trades = [
        trade(5, "300", when=utc(3, 4, 9)),
        trade(6, "300", when=utc(3, 3, 9)),  # earlier close wins the best tie
        trade(7, "-200", when=utc(3, 5, 9)),
        trade(8, "-200", when=utc(3, 2, 9)),  # earlier close wins the worst tie
    ]
    m = compute_metrics(trades, SIZES)
    assert m.best_trade is not None and m.best_trade.id == 6  # noqa: PT018
    assert m.worst_trade is not None and m.worst_trade.id == 8  # noqa: PT018


def test_empty_period() -> None:
    m = compute_metrics([], SIZES)
    assert (m.trades, m.wins, m.losses, m.breakeven, m.violations, m.r_n) == (0, 0, 0, 0, 0, 0)
    assert (m.net_pnl, m.total_r, m.max_drawdown) == (D("0"), D("0"), D("0"))
    for ratio in (
        m.net_pnl_pct,
        m.win_rate,
        m.avg_win_r,
        m.avg_loss_r,
        m.expectancy_r,
        m.profit_factor,
        m.max_drawdown_pct,
        m.best_trade,
        m.worst_trade,
    ):
        assert ratio is None


def test_trades_without_any_r_give_zero_total_and_no_r_ratios() -> None:
    m = compute_metrics([trade(1, "100"), trade(2, "-40")], SIZES)
    assert (m.total_r, m.r_n) == (D("0"), 0)
    assert m.avg_win_r is None and m.avg_loss_r is None and m.expectancy_r is None  # noqa: PT018
    assert m.win_rate == D("50")


def test_percent_base_is_only_accounts_that_have_a_trade() -> None:
    sizes = {1: D("10000"), 2: D("40000")}
    m = compute_metrics([trade(1, "100"), trade(2, "-50")], sizes)  # account 1 only
    assert m.net_pnl_pct == D("0.5")  # 50 / 10000 * 100
    assert m.max_drawdown_pct == D("0.5")  # 50 / 10000 * 100


def test_percent_is_none_when_a_used_account_has_no_size() -> None:
    m = compute_metrics([trade(1, "100"), trade(2, "50", account=9)], SIZES)
    assert m.net_pnl == D("150")
    assert m.net_pnl_pct is None and m.max_drawdown_pct is None  # noqa: PT018


def test_compute_metrics_does_not_mutate_or_reorder_the_input() -> None:
    trades = list(reversed(week()))
    before = list(trades)
    compute_metrics(trades, SIZES)
    assert trades == before


# --- breakdowns ------------------------------------------------------------------------------


def test_symbol_breakdown_groups_sorted_by_key() -> None:
    b = breakdown(week(), "symbol")
    assert [g.key for g in b.groups] == ["EURUSD", "GER30", "XAUUSD"]
    eur, ger, xau = b.groups
    # EURUSD: t6 +100 (no R), t8 +50 R1 -> 150, R 1, 2/2 wins
    assert (eur.trades, eur.net_pnl, eur.total_r, eur.win_rate) == (2, D("150"), D("1"), D("100"))
    # GER30: t3 +300, t4 -100, t7 -200 -> 0, R 3 - 1 - 2 = 0, 1/3 wins
    assert (ger.trades, ger.net_pnl, ger.total_r) == (3, D("0"), D("0"))
    close(ger.win_rate, "33.3333")
    # XAUUSD: t1 +200, t2 -100, t5 0 -> 100, R 2 - 1 + 0 = 1, 1/3 wins (breakeven not a win)
    assert (xau.trades, xau.net_pnl, xau.total_r) == (3, D("100"), D("1"))
    close(xau.win_rate, "33.3333")
    assert (b.filled, b.total) == (8, 8)


def test_entry_model_breakdown_has_a_none_group_last_and_coverage() -> None:
    b = breakdown(week(), "entry_model")
    assert [g.key for g in b.groups] == ["FVG", "OB", None]
    fvg, ob, empty = b.groups
    assert (fvg.trades, fvg.net_pnl, fvg.total_r, fvg.win_rate) == (2, D("200"), D("2"), D("50"))
    # OB: t1 +200, t2 -100, t7 -200 -> -100, R 2 - 1 - 2 = -1
    assert (ob.trades, ob.net_pnl, ob.total_r) == (3, D("-100"), D("-1"))
    # None: t5 0, t6 +100 (no R), t8 +50 R1 -> 150, R 0 + 1 = 1, 2/3 wins
    assert (empty.trades, empty.net_pnl, empty.total_r) == (3, D("150"), D("1"))
    close(empty.win_rate, "66.6667")
    assert (b.filled, b.total) == (5, 8)


def test_breakdown_of_booleans_hours_and_weekdays() -> None:
    trades = [
        trade(1, "10", "1", hour=9, weekday=0, followed_plan=True),
        trade(2, "-5", "-1", hour=9, weekday=1, followed_plan=False),
        trade(3, "20", "2", hour=14, weekday=1, followed_plan=True),
        trade(4, "1", None, hour=None, weekday=None, followed_plan=None),
    ]
    by_hour = {g.key: g for g in breakdown(trades, "hour").groups}
    assert set(by_hour) == {9, 14, None}
    assert by_hour[9].net_pnl == D("5") and by_hour[9].trades == 2  # noqa: PT018
    by_plan = {g.key: g for g in breakdown(trades, "followed_plan").groups}
    assert by_plan[True].net_pnl == D("30") and by_plan[False].net_pnl == D("-5")  # noqa: PT018
    assert by_plan[None].trades == 1
    assert (breakdown(trades, "weekday").filled, breakdown(trades, "weekday").total) == (3, 4)


def test_breakdowns_covers_every_field_and_rejects_unknown_ones() -> None:
    result = breakdowns(week())
    assert tuple(result) == BREAKDOWN_FIELDS
    assert all(result[f].total == 8 for f in BREAKDOWN_FIELDS)
    with pytest.raises(ValueError):  # noqa: PT011
        breakdown(week(), "net_pnl")


def test_breakdown_of_nothing_has_no_groups() -> None:
    b = breakdown([], "symbol")
    assert b.groups == () and (b.filled, b.total) == (0, 0)  # noqa: PT018


# --- rules and bias --------------------------------------------------------------------------


def test_rule_section_counts_a_trade_with_two_violations_in_both_rules() -> None:
    s = rule_section(week())
    assert [r.rule_key for r in s.rules] == ["risk_high", "rr_low"]
    risk, rr = s.rules
    # risk_high: t2 (-100), t4 (-100), t7 twice (-200) -> 4 occurrences, 3 trades, pnl -400
    assert (risk.violations, risk.trades, risk.pnl) == (4, 3, D("-400"))
    # rr_low: t2 (-100) and t6 (+100) -> 2 occurrences, 2 trades, pnl 0
    assert (rr.violations, rr.trades, rr.pnl) == (2, 2, D("0"))
    # distinct trades with any violation: t2, t4, t6, t7 -> -100 - 100 + 100 - 200 = -300
    assert (s.violated_trades, s.violated_pnl) == (4, D("-300"))


def test_rule_section_without_violations() -> None:
    s = rule_section([trade(1, "10"), trade(2, "-3")])
    assert s.rules == () and (s.violated_trades, s.violated_pnl) == (0, D("0"))  # noqa: PT018
    assert rule_section([]).rules == ()


def test_bias_accuracy_counts_only_marked_entries() -> None:
    s = bias_section([], [True, True, False, None])
    assert (s.marked, s.total) == (3, 4)
    close(s.accuracy, "66.6667")  # 2 / 3 * 100
    assert bias_section([], [True, False]).accuracy == D("50")


def test_bias_accuracy_is_none_without_marked_entries() -> None:
    assert bias_section([], [None, None]).accuracy is None
    s = bias_section([], [])
    assert s.accuracy is None and (s.marked, s.total) == (0, 0)  # noqa: PT018


def test_bias_aligned_vs_counter_pnl_and_r() -> None:
    s = bias_section(week(), [])
    # aligned t1 +200 R2, t3 +300 R3, t8 +50 R1 -> 550, R 6
    assert (s.aligned.trades, s.aligned.net_pnl, s.aligned.total_r) == (3, D("550"), D("6"))
    # counter t2 -100 R-1, t4 -100 R-1 -> -200, R -2
    assert (s.counter.trades, s.counter.net_pnl, s.counter.total_r) == (2, D("-200"), D("-2"))


# --- norm and deviation ----------------------------------------------------------------------
# history [45, 55, 45, 55]: mean 50, population variance (25 + 25 + 25 + 25) / 4 = 25, SD 5.

HIST = [D("45"), D("55"), D("45"), D("55")]


def test_norm_reports_mean_and_population_sd() -> None:
    r = norm_deviation("win_rate", D("50"), HIST)
    assert (r.value, r.norm_mean, r.norm_sd, r.deviation) == (D("50"), D("50"), D("5"), None)


@pytest.mark.parametrize("history", [[], [D("50")], [D("45"), D("55")]])
def test_fewer_than_three_periods_gives_no_norm_and_no_highlight(history: list[Decimal]) -> None:
    r = norm_deviation("win_rate", D("0"), history)
    assert r.norm_mean is None and r.norm_sd is None and r.deviation is None  # noqa: PT018


def test_zero_standard_deviation_gives_no_highlight() -> None:
    r = norm_deviation("win_rate", D("10"), [D("50"), D("50"), D("50")])
    assert r.norm_sd == D("0") and r.deviation is None  # noqa: PT018


def test_worse_win_rate_beyond_one_sd_is_worse() -> None:
    assert norm_deviation("win_rate", D("44"), HIST).deviation == "worse"  # < 50 - 5
    assert norm_deviation("win_rate", D("40"), HIST).deviation == "worse"


def test_better_total_r_beyond_one_sd_is_better() -> None:
    assert norm_deviation("total_r", D("56"), HIST).deviation == "better"  # > 50 + 5


def test_exactly_on_the_threshold_or_inside_is_not_highlighted() -> None:
    assert norm_deviation("win_rate", D("45"), HIST).deviation is None
    assert norm_deviation("win_rate", D("55"), HIST).deviation is None
    assert norm_deviation("win_rate", D("50"), HIST).deviation is None


def test_max_drawdown_lower_is_better() -> None:
    assert norm_deviation("max_drawdown", D("60"), HIST).deviation == "worse"
    assert norm_deviation("max_drawdown", D("40"), HIST).deviation == "better"
    assert norm_deviation("max_drawdown_pct", D("60"), HIST).deviation == "worse"
    assert norm_deviation("violations", D("40"), HIST).deviation == "better"


@pytest.mark.parametrize("metric", sorted(HIGHER_IS_BETTER))
def test_every_higher_is_better_metric(metric: str) -> None:
    assert norm_deviation(metric, D("40"), HIST).deviation == "worse"
    assert norm_deviation(metric, D("60"), HIST).deviation == "better"


@pytest.mark.parametrize("metric", sorted(LOWER_IS_BETTER))
def test_every_lower_is_better_metric(metric: str) -> None:
    assert norm_deviation(metric, D("60"), HIST).deviation == "worse"
    assert norm_deviation(metric, D("40"), HIST).deviation == "better"


def test_metric_sets_are_disjoint_and_trades_is_never_highlighted() -> None:
    assert not HIGHER_IS_BETTER & LOWER_IS_BETTER
    assert "trades" not in HIGHER_IS_BETTER | LOWER_IS_BETTER
    assert {
        "net_pnl",
        "net_pnl_pct",
        "total_r",
        "win_rate",
        "avg_win_r",
        "avg_loss_r",
        "expectancy_r",
        "profit_factor",
    } == HIGHER_IS_BETTER
    assert {"max_drawdown", "max_drawdown_pct", "violations"} == LOWER_IS_BETTER
    r = norm_deviation("trades", D("1000"), HIST)
    assert r.deviation is None and r.norm_mean == D("50")  # noqa: PT018


def test_custom_k_widens_or_narrows_the_band() -> None:
    assert norm_deviation("win_rate", D("46"), HIST).deviation is None  # band 45..55
    assert norm_deviation("win_rate", D("46"), HIST, k=D("0.5")).deviation == "worse"  # < 47.5
    assert norm_deviation("win_rate", D("40"), HIST, k=D("2")).deviation is None  # band 40..60
    assert norm_deviation("win_rate", D("39"), HIST, k=D("2")).deviation == "worse"


def test_missing_value_or_unknown_metric() -> None:
    assert norm_deviation("profit_factor", None, HIST).deviation is None
    with pytest.raises(ValueError):  # noqa: PT011
        norm_deviation("sharpe", D("1"), HIST)


def test_metric_series_is_per_period_with_trades_oldest_first() -> None:
    trades = [
        trade(1, "100", "1", utc(3, 2, 9)),  # week 03-02: +100, -50
        trade(2, "-50", "-0.5", utc(3, 3, 9)),
        trade(3, "30", "0.3", utc(3, 10, 9)),  # week 03-09: +30 (no loss)
        trade(4, "-20", "-0.2", utc(3, 24, 9)),  # week 03-23: -20 (03-16 has no trade)
    ]
    assert metric_series(trades, "weekly", SIZES, "net_pnl") == (D("50"), D("30"), D("-20"))
    # profit factor: 100 / 50 = 2; week 2 has no loss -> dropped; week 4 no win -> 0
    assert metric_series(trades, "weekly", SIZES, "profit_factor") == (D("2"), D("0"))
    assert metric_series(trades, "monthly", SIZES, "trades") == (D("4"),)
    assert metric_series([], "weekly", SIZES, "net_pnl") == ()


def test_norm_window_is_sixty_weekdays_before_the_period_aligned_to_its_kind() -> None:
    # 60 weekdays = 12 weeks = 84 days when the period starts on a weekday (a Monday: aligned).
    assert norm_window_start("weekly", date(2026, 3, 2)) == date(2025, 12, 8)
    # Wed 2026-04-01: 60 weekdays back is Wed 01-07 -> monthly window starts on Thu 2026-01-01.
    assert norm_window_start("monthly", date(2026, 4, 1)) == date(2026, 1, 1)
    # Sat 2026-08-01: weekdays back from Fri 07-31; the 60th is Mon 05-11 -> month start 05-01.
    assert norm_window_start("monthly", date(2026, 8, 1)) == date(2026, 5, 1)
    assert norm_window_start("weekly", date(2026, 8, 3)) == date(2026, 5, 11)  # Mon, 84 days back


def test_norm_window_trades_are_inside_window_and_before_the_period() -> None:
    start = date(2026, 3, 2)
    trades = [
        trade(1, "1", when=utc(12, 7, 22, 59, y=2025)),  # Sun 2025-12-07 23:59 Brussels: too old
        trade(2, "1", when=utc(12, 7, 23, 0, y=2025)),  # Mon 2025-12-08 00:00: first in window
        trade(3, "1", when=utc(3, 1, 22, 59)),  # Sun 03-01 23:59: last before the period
        trade(4, "1", when=utc(3, 1, 23, 0)),  # Mon 03-02 00:00: in the period itself
    ]
    assert [t.id for t in norm_window_trades(trades, "weekly", start)] == [2, 3]


def test_monthly_norm_window_keeps_the_whole_first_month() -> None:
    trades = [
        trade(1, "10", "1", utc(12, 31, 12, y=2025)),  # before the window (Dec)
        trade(2, "20", "1", utc(1, 2, 12)),  # Jan 2..6 are before the old Jan 7 cut-off
        trade(3, "-5", "-1", utc(1, 6, 12)),
        trade(4, "7", "1", utc(2, 10, 12)),
        trade(5, "8", "1", utc(3, 10, 12)),
        trade(6, "99", "1", utc(4, 1, 12)),  # the period itself
    ]
    window = norm_window_trades(trades, "monthly", date(2026, 4, 1))
    assert [t.id for t in window] == [2, 3, 4, 5]
    # Jan 20 - 5 = 15, Feb 7, Mar 8 -> 3 full months
    assert metric_series(window, "monthly", SIZES, "net_pnl") == (D("15"), D("7"), D("8"))


def week_of(first_day: int, rows: list[tuple[str, str]]) -> list[DigestTrade]:
    """Four trades Mon..Thu of the March 2026 week starting on day `first_day` (pnl, R)."""
    base = first_day * 10
    return [
        trade(base + i, pnl, r, utc(3, first_day, 9) + timedelta(days=i))
        for i, (pnl, r) in enumerate(rows)
    ]


def test_end_to_end_norm_from_trade_history_flags_worse_win_rate_and_better_total_r() -> None:
    win, loss = ("100", "1"), ("-100", "-1")
    history = [
        *week_of(2, [win, win, loss, loss]),  # win rate 50, total R 0
        *week_of(9, [win, win, win, loss]),  # 75, R 1 + 1 + 1 - 1 = 2
        *week_of(16, [win, loss, win, loss]),  # 50, R 0
        *week_of(23, [win, win, loss, win]),  # 75, R 2
    ]
    # The week under test: 1 win of 4 = 25 % (worse), but R +5 - 0.5 x 3 = 3.5 (better).
    current = week_of(30, [("500", "5"), ("-10", "-0.5"), ("-10", "-0.5"), ("-10", "-0.5")])
    old = trade(900, "1000", "9", utc(10, 1, 9, y=2025))  # outside the 60-weekday window
    everything = [old, *history, *current]
    start = date(2026, 3, 30)

    window = norm_window_trades(everything, "weekly", start)
    assert [t.id for t in window] == [t.id for t in history]  # old and current are excluded
    cur = compute_metrics(trades_in_period(everything, "weekly", start), SIZES)

    wr_history = metric_series(window, "weekly", SIZES, "win_rate")
    assert wr_history == (D("50"), D("75"), D("50"), D("75"))
    # mean 62.5, deviations +-12.5 -> population SD 12.5, band 50..75; 25 < 50 -> worse
    wr = norm_deviation("win_rate", cur.win_rate, wr_history)
    assert (wr.norm_mean, wr.norm_sd, wr.deviation) == (D("62.5"), D("12.5"), "worse")

    r_history = metric_series(window, "weekly", SIZES, "total_r")
    assert r_history == (D("0"), D("2"), D("0"), D("2"))
    # mean 1, SD 1, band 0..2; 3.5 > 2 -> better
    tr = norm_deviation("total_r", cur.total_r, r_history)
    assert (tr.norm_mean, tr.norm_sd, tr.deviation) == (D("1"), D("1"), "better")


# --- charts ----------------------------------------------------------------------------------


ORIGIN = utc(3, 1, 23)  # Mon 2026-03-02 00:00 Brussels (CET) as a UTC instant
START = date(2026, 3, 2)


def test_equity_combined_and_per_account_start_from_zero() -> None:
    c = equity_curves(week(), START)
    # origin (0) then, in (close, id) order, running: 200, 100, 400, 300, 300, 400, 200, 250
    assert [p.cum_pnl for p in c.combined] == [
        D(x) for x in ("0", "200", "100", "400", "300", "300", "400", "200", "250")
    ]
    assert [p.time for p in c.combined] == [ORIGIN, *[t.close_time for t in week()]]
    # account 1: origin, then t1 +200, t2 -100, t5 0, t6 +100 -> 200, 100, 100, 200
    assert [p.cum_pnl for p in c.by_account[1]] == [D(x) for x in ("0", "200", "100", "100", "200")]
    # account 2: origin, then t3 +300, t4 -100, t7 -200, t8 +50 -> 300, 200, 0, 50
    assert [p.cum_pnl for p in c.by_account[2]] == [D(x) for x in ("0", "300", "200", "0", "50")]
    assert c.by_account[1][0].time == ORIGIN and c.by_account[2][0].time == ORIGIN  # noqa: PT018
    assert set(c.by_account) == {1, 2}


def test_equity_origin_follows_brussels_midnight_in_summer_time() -> None:
    c = equity_curves([trade(1, "5", when=utc(4, 7, 9))], date(2026, 4, 6))
    assert c.combined[0].time == utc(4, 5, 22)  # Mon 00:00 CEST (+2)
    assert c.combined[0].cum_pnl == D("0")


def test_equity_by_account_is_read_only() -> None:
    c = equity_curves(week(), START)
    with pytest.raises(TypeError):
        c.by_account[3] = ()  # type: ignore[index]


def test_breakdowns_result_is_read_only() -> None:
    result = breakdowns(week())
    with pytest.raises(TypeError):
        result["symbol"] = result["hour"]  # type: ignore[index]


def test_equity_sorts_unordered_input_and_ties_by_id() -> None:
    same = utc(3, 2, 9)
    c = equity_curves([trade(2, "-10", when=same), trade(1, "5", when=same)], START)
    assert [p.cum_pnl for p in c.combined] == [D("0"), D("5"), D("-5")]


def test_equity_of_nothing_is_only_the_origin() -> None:
    c = equity_curves([], START)
    assert [(p.time, p.cum_pnl) for p in c.combined] == [(ORIGIN, D("0"))]
    assert c.by_account == {}


def test_r_distribution_half_r_buckets_with_edge_folding() -> None:
    rs = ["-5", "-3", "-0.1", "0", "0.49", "0.5", "2", "7"]
    trades = [trade(i, "1", r) for i, r in enumerate(rs, start=1)] + [trade(99, "1", None)]
    buckets = r_distribution(trades)
    # clamp to [-3, 3]; min bucket -3.0, max bucket 3.0 -> 13 contiguous buckets
    assert len(buckets) == 13
    assert buckets[0].lower == D("-3.0") and buckets[0].upper == D("-2.5")  # noqa: PT018
    assert buckets[-1].lower == D("3.0") and buckets[-1].upper == D("3.5")  # noqa: PT018
    counts = {b.lower: b.count for b in buckets}
    assert counts[D("-3.0")] == 2  # -5 (folded) and -3
    assert counts[D("-0.5")] == 1  # -0.1
    assert counts[D("0.0")] == 2  # 0 and 0.49
    assert counts[D("0.5")] == 1  # 0.5 starts a new bucket
    assert counts[D("2.0")] == 1
    assert counts[D("3.0")] == 1  # 7 folded into the top edge bucket
    assert counts[D("1.0")] == 0  # empty bucket between min and max is kept
    assert sum(counts.values()) == 8  # the trade without R is not counted


def test_r_distribution_of_the_fixture_week() -> None:
    buckets = r_distribution(week())  # R: 2, -1, 3, -1, 0, -2, 1 (n = 7)
    assert [b.lower for b in buckets] == [
        D(x) for x in ["-2", "-1.5", "-1", "-0.5", "0", "0.5", "1", "1.5", "2", "2.5", "3"]
    ]
    assert [b.count for b in buckets] == [1, 0, 2, 0, 1, 0, 1, 0, 1, 0, 1]


def test_r_distribution_without_r_is_empty() -> None:
    assert r_distribution([trade(1, "5")]) == ()
    assert r_distribution([]) == ()


def test_hour_heatmap_cells_sorted_and_skipping_unknown_slots() -> None:
    trades = [
        trade(1, "10", hour=9, weekday=0),
        trade(2, "-4", hour=9, weekday=0),
        trade(3, "7", hour=14, weekday=0),
        trade(4, "20", hour=9, weekday=2),
        trade(5, "99", hour=None, weekday=1),
        trade(6, "99", hour=9, weekday=None),
    ]
    cells = hour_heatmap(trades)
    assert [(c.weekday, c.hour, c.trades, c.net_pnl) for c in cells] == [
        (0, 9, 2, D("6")),
        (0, 14, 1, D("7")),
        (2, 9, 1, D("20")),
    ]
    assert hour_heatmap([]) == ()


def test_results_are_frozen() -> None:
    m = compute_metrics(week(), SIZES)
    with pytest.raises(AttributeError):
        m.trades = 1  # type: ignore[misc]
    with pytest.raises(AttributeError):
        replace(week()[0]).id = 5  # type: ignore[misc]

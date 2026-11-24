"""cTrader phase c, c5: MAE / MFE from 2145 ticks and 2137 M1 trendbars (no database).

The definitions are those of MT5 M8-16 (`app.services.excursions`, `app.domain.excursion`):
ticks only below 2 h (source TICKS), otherwise ticks for the entry and exit minute and M1 bars
in between (source M1_TICKS); a long is measured on BID, a short on ASK.

cTrader trendbars are BID only, so a short adds the median ASK-BID spread of the entry and exit
tick samples to every bar (docs/DECISIONS.md, 2026-11-24).

Expected API of the new module ``app/ctrader/excursions.py`` (written after these tests):

    decode_trendbars(entries: Sequence[object]) -> tuple[CtBar, ...]      # CtBar: time, low, high
    merge_bid_ask(bids: Sequence[CtTick], asks: Sequence[CtTick]) -> tuple[PriceSample, ...]
    median_spread(samples: Sequence[PriceSample]) -> Decimal | None
    bar_samples(bars: Sequence[CtBar], spread: Decimal) -> tuple[PriceSample, ...]
    async series_for_ctrader(connection, ctid, symbol_id, target, point, now) -> Series
    async fetch_ctrader_series(connection, ctid, targets, symbol_ids, points, now,
                               budget_s=BUDGET_S) -> Fetched
    BUDGET_S: float   (0 < BUDGET_S <= 20)

ASSUMPTIONS (Open API docs, to confirm on the first live run; the fixtures here are synthetic):
2137 GetTrendbarsReq carries ``ctidTraderAccountId``, ``symbolId``, ``period`` (1 = M1),
``fromTimestamp`` and ``toTimestamp`` (ms); the answer lists ``trendbar[]`` with an absolute
``low`` and unsigned ``deltaOpen`` / ``deltaClose`` / ``deltaHigh`` above it, prices in 1/100000,
``utcTimestampInMinutes`` = start of the bar in epoch minutes (UTC).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.excursions import (
    BUDGET_S,
    bar_samples,
    decode_trendbars,
    fetch_ctrader_series,
    median_spread,
    merge_bid_ask,
    series_for_ctrader,
)
from app.ctrader.ticks import CtTick
from app.domain.excursion import bar, tick
from app.models.enums import Direction, ExcursionSource
from app.services.excursions import (
    UNAVAILABLE_AFTER,
    ExcursionTarget,
    Series,
    evaluate,
)
from tests.ctrader_fakes import CTID, FakeConnector, FakeTransport, no_sleep
from tests.ctrader_phase_c_fakes import ASK, BID, M1, Bar, PhaseCServer, Point

D = Decimal
DAY = datetime(2026, 11, 23, tzinfo=UTC)
POINT = D("0.00001")
EURUSD_ID, XAUUSD_ID = 1, 41


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


def ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


# --- builders --------------------------------------------------------------------------------


def quotes(*rows: tuple[datetime, str, str]) -> dict[int, list[Point]]:
    """(time, bid, ask) rows -> the {BID: [...], ASK: [...]} the fake server serves."""
    return {
        BID: [(ms(t), D(b)) for t, b, _a in rows],
        ASK: [(ms(t), D(a)) for t, _b, a in rows],
    }


def m1_bar(start: datetime, high: str, low: str) -> Bar:
    """A BID M1 bar that opens and closes at its low (only high and low matter here)."""
    return (ms(start), D(low), D(high), D(low), D(low))


def target(
    direction: Direction,
    open_at: datetime,
    close_at: datetime | None,
    *,
    entry: str = "1.08512",
    sl: str | None = "1.08412",
) -> ExcursionTarget:
    return ExcursionTarget(
        trade_id=1,
        broker_symbol="EURUSD",
        direction=direction,
        entry_price=D(entry),
        initial_sl=D(sl) if sl is not None else None,
        open_time=open_at,
        close_time=close_at,
    )


def run_async[T](server: PhaseCServer, body: Callable[[CtraderConnection], Awaitable[T]]) -> T:
    async def scenario() -> T:
        transport: FakeTransport = server.transport()
        connection = CtraderConnection("wss://fake", FakeConnector(transport), sleep=no_sleep)
        await connection.start()
        try:
            return await body(connection)
        finally:
            await connection.close()

    return asyncio.run(scenario())


def read_series(server: PhaseCServer, trade: ExcursionTarget, now: datetime) -> Series:
    return run_async(
        server,
        lambda connection: series_for_ctrader(connection, CTID, EURUSD_ID, trade, POINT, now),
    )


def final_values(series: Series, now: datetime) -> Any:
    outcome, result = evaluate(series, now)
    assert outcome == "final"
    assert result is not None
    return result


# --- pure: trendbars -------------------------------------------------------------------------


def test_decode_trendbars_high_is_low_plus_delta_high() -> None:
    entries = [
        {
            "low": 108312,
            "deltaOpen": 20,
            "deltaClose": 45,
            "deltaHigh": 88,
            "utcTimestampInMinutes": 29923800,  # 2026-11-23 10:00 UTC
        },
        {"low": 108400, "deltaHigh": 0, "utcTimestampInMinutes": 29923801},
    ]

    first, second = decode_trendbars(entries)

    assert (first.time, first.low, first.high) == (at(10), D("1.08312"), D("1.08400"))
    assert (second.time, second.low, second.high) == (at(10, 1), D("1.08400"), D("1.08400"))
    assert isinstance(first.high, Decimal)  # exact, never a float


def test_decode_trendbars_empty_is_empty() -> None:
    assert decode_trendbars([]) == ()


@pytest.mark.parametrize(
    "entries",
    [
        ["not a dict"],
        [{"deltaHigh": 1, "utcTimestampInMinutes": 1}],  # no low
        [{"low": 1, "utcTimestampInMinutes": 1}],  # no deltaHigh
        [{"low": 1, "deltaHigh": 1}],  # no time
        [{"low": "abc", "deltaHigh": 1, "utcTimestampInMinutes": 1}],
        [{"low": 1, "deltaHigh": -5, "utcTimestampInMinutes": 1}],  # high below low
        [{"low": 0, "deltaHigh": 1, "utcTimestampInMinutes": 1}],  # no price
    ],
)
def test_decode_trendbars_refuses_malformed_entries(entries: list[Any]) -> None:
    with pytest.raises(CtraderError) as caught:
        decode_trendbars(entries)
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


def test_bar_samples_add_the_spread_to_the_ask_side_only() -> None:
    bars = decode_trendbars([{"low": 108312, "deltaHigh": 88, "utcTimestampInMinutes": 29923800}])

    (sample,) = bar_samples(bars, D("0.00020"))

    assert sample == bar(at(10), D("1.08400"), D("1.08312"), D("0.00020"))
    assert (sample.bid_high, sample.bid_low) == (D("1.08400"), D("1.08312"))
    assert (sample.ask_high, sample.ask_low) == (D("1.08420"), D("1.08332"))


def test_bar_samples_without_spread_keep_the_middle_bid() -> None:
    bars = decode_trendbars([{"low": 108312, "deltaHigh": 88, "utcTimestampInMinutes": 1}])

    (sample,) = bar_samples(bars, D(0))

    assert (sample.ask_high, sample.ask_low) == (sample.bid_high, sample.bid_low)


# --- pure: BID + ASK ticks -------------------------------------------------------------------


def test_merge_bid_ask_pairs_ticks_by_timestamp() -> None:
    bids = [CtTick(at(9, 1), D("1.0850")), CtTick(at(9, 2), D("1.0852"))]
    asks = [CtTick(at(9, 1), D("1.0851")), CtTick(at(9, 2), D("1.0854"))]

    merged = merge_bid_ask(bids, asks)

    assert merged == (
        tick(at(9, 1), D("1.0850"), D("1.0851")),
        tick(at(9, 2), D("1.0852"), D("1.0854")),
    )


def test_merge_bid_ask_carries_the_last_quote_of_the_other_side_forward() -> None:
    bids = [CtTick(at(9, 1), D("1.0850")), CtTick(at(9, 3), D("1.0856"))]
    asks = [CtTick(at(9, 2), D("1.0853"))]

    merged = merge_bid_ask(bids, asks)

    # 09:01 has no ASK yet: no sample. 09:02 pairs the new ASK with the last BID, 09:03 the
    # new BID with the last ASK.
    assert merged == (
        tick(at(9, 2), D("1.0850"), D("1.0853")),
        tick(at(9, 3), D("1.0856"), D("1.0853")),
    )


def test_merge_bid_ask_sorts_its_input_and_keeps_millisecond_times() -> None:
    late = at(9, 1).replace(microsecond=250_000)
    bids = [CtTick(late, D("1.0852")), CtTick(at(9, 1), D("1.0850"))]
    asks = [CtTick(at(9, 1), D("1.0851"))]

    merged = merge_bid_ask(bids, asks)

    assert [s.time for s in merged] == [at(9, 1), late]
    assert merged[1] == tick(late, D("1.0852"), D("1.0851"))


@pytest.mark.parametrize(
    ("bids", "asks"),
    [
        ([], []),
        ([CtTick(at(9), D("1.08"))], []),
        ([], [CtTick(at(9), D("1.08"))]),
    ],
)
def test_merge_bid_ask_needs_both_sides(bids: list[CtTick], asks: list[CtTick]) -> None:
    assert merge_bid_ask(bids, asks) == ()


def test_median_spread_odd_even_and_empty() -> None:
    def sample(spread: str) -> Any:
        return tick(at(9), D("1.08"), D("1.08") + D(spread))

    assert median_spread([sample("0.0001"), sample("0.0003"), sample("0.0002")]) == D("0.0002")
    assert median_spread([sample("0.0001"), sample("0.0003")]) == D("0.0002")
    assert median_spread([sample("0.0005")]) == D("0.0005")
    assert median_spread([]) is None


# --- series: ticks only (< 2 h), long -------------------------------------------------------

OPEN_A, CLOSE_A = at(9), at(10, 30)  # 90 min, EURUSD buy 1.08512, SL 1.08412 (risk 0.001)
TICKS_A = quotes(
    (at(9), "1.08512", "1.08522"),
    (at(9, 10), "1.08462", "1.08472"),  # lowest BID: 0.0005 = 0.5 R against
    (at(9, 40), "1.08762", "1.08772"),  # highest BID: 0.0025 = 2.5 R for
    (at(9, 50), "1.08700", "1.08990"),  # highest ASK: a long must ignore it
    (at(10, 30), "1.08712", "1.08722"),
)


def test_long_under_two_hours_uses_ticks_only_and_matches_the_hand_calculation() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})
    trade = target(Direction.BUY, OPEN_A, CLOSE_A)

    series = read_series(server, trade, at(10, 40))

    assert series.source is ExcursionSource.TICKS
    assert series.complete is True
    assert series.end_time == CLOSE_A
    assert series.point == POINT
    assert len(series.samples) == 5
    result = final_values(series, at(10, 40))
    assert (result.mfe_price, result.mfe_time) == (D("1.08762"), at(9, 40))
    assert (result.mfe_r, result.mfe_points) == (D("2.5000"), D("250.0"))
    assert (result.mae_price, result.mae_time) == (D("1.08462"), at(9, 10))
    assert (result.mae_r, result.mae_points) == (D("0.5000"), D("50.0"))


def test_ticks_only_trade_reads_both_sides_over_the_trade_and_no_bars() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})

    read_series(server, target(Direction.BUY, OPEN_A, CLOSE_A), at(10, 40))

    asked = {(kind, lo, hi) for sid, kind, lo, hi in server.tick_requests if sid == EURUSD_ID}
    assert {kind for kind, _lo, _hi in asked} == {BID, ASK}
    assert all(lo <= ms(OPEN_A) and hi >= ms(CLOSE_A) for _kind, lo, hi in asked)
    assert server.trendbar_requests == []


def test_a_tick_exactly_at_open_and_close_is_inside_the_window() -> None:
    rows = quotes((OPEN_A, "1.08512", "1.08522"), (CLOSE_A, "1.08812", "1.08822"))

    series = read_series(
        PhaseCServer(ticks={"EURUSD": rows}), target(Direction.BUY, OPEN_A, CLOSE_A), at(11)
    )

    assert final_values(series, at(11)).mfe_r == D("3.0000")


@pytest.mark.parametrize(
    ("case", "rows", "close_at", "mfe_r", "mae_r"),
    [
        # TP 1.08812 = 3 R hit at the close: MFE is at least the TP's RR.
        (
            "take profit",
            [(at(9, 10), "1.08462", "1.08472"), (at(10), "1.08812", "1.08822")],
            at(10),
            D("3.0000"),
            D("0.5000"),
        ),
        # +1.5 R first, then the stop (1.08412) is hit: MAE is the full 1 R.
        (
            "stop after a favourable move",
            [(at(9, 10), "1.08662", "1.08672"), (at(9, 30), "1.08412", "1.08422")],
            at(9, 30),
            D("1.5000"),
            D("1.0000"),
        ),
        # The market gaps through the stop: the fill 2 R away is the MAE, never capped at 1 R.
        (
            "gap through the stop",
            [(at(9, 0), "1.08512", "1.08522"), (at(9, 30), "1.08312", "1.08322")],
            at(9, 30),
            D("0.0000"),
            D("2.0000"),
        ),
    ],
)
def test_take_profit_stop_and_gap_scenarios(
    case: str, rows: list[tuple[datetime, str, str]], close_at: datetime, mfe_r: Decimal,
    mae_r: Decimal,
) -> None:  # fmt: skip
    server = PhaseCServer(ticks={"EURUSD": quotes(*rows)})

    series = read_series(
        server, target(Direction.BUY, OPEN_A, close_at), close_at + timedelta(minutes=1)
    )

    result = final_values(series, close_at + timedelta(minutes=1))
    assert (result.mfe_r, result.mae_r) == (mfe_r, mae_r), case


def test_take_profit_mfe_is_not_below_the_tp_distance() -> None:
    tp, entry, sl = D("1.08812"), D("1.08512"), D("1.08412")
    rows = quotes((at(9, 20), "1.08560", "1.08570"), (at(10), "1.08812", "1.08822"))

    series = read_series(
        PhaseCServer(ticks={"EURUSD": rows}), target(Direction.BUY, OPEN_A, at(10)), at(11)
    )

    result = final_values(series, at(11))
    assert result.mfe_price >= tp
    assert result.mfe_r >= (tp - entry) / (entry - sl)


def test_a_trade_that_never_went_favourable_has_mfe_zero_at_the_entry() -> None:
    rows = quotes((at(9, 30), "1.08312", "1.08322"))

    series = read_series(
        PhaseCServer(ticks={"EURUSD": rows}), target(Direction.BUY, OPEN_A, at(9, 30)), at(10)
    )

    result = final_values(series, at(10))
    assert (result.mfe_r, result.mfe_price, result.mfe_time) == (D("0.0000"), D("1.08512"), OPEN_A)


def test_missing_initial_sl_gives_points_only_and_no_r() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})

    series = read_series(server, target(Direction.BUY, OPEN_A, CLOSE_A, sl=None), at(10, 40))

    result = final_values(series, at(10, 40))
    assert (result.mfe_r, result.mae_r) == (None, None)
    assert (result.mfe_points, result.mae_points) == (D("250.0"), D("50.0"))


# --- series: M1 bars + edge ticks (> 2 h) ---------------------------------------------------

OPEN_B, CLOSE_B = at(9, 0, 30), at(11, 30, 30)  # 2 h 30 min: bars between 09:01 and 11:30
MIDDLE_FROM, MIDDLE_TO = at(9, 1), at(11, 30)
EDGE_TICKS_SHORT = quotes(  # spreads .0001 / .0003 / .0002 / .0002 -> median .0002
    (at(9, 0, 40), "1.08502", "1.08512"),
    (at(11, 30, 10), "1.08392", "1.08422"),
    (at(11, 30, 20), "1.08400", "1.08420"),
    (CLOSE_B, "1.08410", "1.08430"),
)
BARS_SHORT = [
    m1_bar(at(9, 30), "1.08520", "1.08500"),
    m1_bar(at(10, 15), "1.08400", "1.08312"),  # lowest bid 1.08312 -> ask 1.08332
    m1_bar(at(10, 45), "1.08562", "1.08480"),  # highest bid 1.08562 -> ask 1.08582
]


def test_short_over_two_hours_adds_the_median_tick_spread_to_the_bars() -> None:
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})
    trade = target(Direction.SELL, OPEN_B, CLOSE_B, sl="1.08612")

    series = read_series(server, trade, at(11, 45))

    assert series.source is ExcursionSource.M1_TICKS
    assert series.complete is True
    result = final_values(series, at(11, 45))
    # short: favourable = lowest ASK = 1.08312 + 0.0002 = 1.08332 -> 0.0018 / 0.001 = 1.8 R
    assert (result.mfe_price, result.mfe_time) == (D("1.08332"), at(10, 15))
    assert (result.mfe_r, result.mfe_points) == (D("1.8000"), D("180.0"))
    # adverse = highest ASK = 1.08562 + 0.0002 = 1.08582 -> 0.0007 / 0.001 = 0.7 R
    assert (result.mae_price, result.mae_time) == (D("1.08582"), at(10, 45))
    assert (result.mae_r, result.mae_points) == (D("0.7000"), D("70.0"))


def test_long_over_two_hours_uses_the_bars_as_bid_and_ignores_the_spread() -> None:
    wide = quotes(  # a 0.003 spread everywhere: must not leak into a long's numbers
        (at(9, 0, 40), "1.08512", "1.08812"),
        (at(11, 30, 10), "1.08700", "1.09000"),
        (CLOSE_B, "1.08702", "1.09002"),
    )
    bars = [m1_bar(at(10), "1.08792", "1.08600"), m1_bar(at(10, 20), "1.08600", "1.08432")]
    server = PhaseCServer(ticks={"EURUSD": wide}, bars={"EURUSD": bars})

    series = read_series(server, target(Direction.BUY, OPEN_B, CLOSE_B), at(11, 45))

    assert series.source is ExcursionSource.M1_TICKS
    result = final_values(series, at(11, 45))
    assert (result.mfe_price, result.mfe_time, result.mfe_r) == (D("1.08792"), at(10), D("2.8000"))
    assert (result.mae_price, result.mae_time) == (D("1.08432"), at(10, 20))
    assert result.mae_r == D("0.8000")


def test_ticks_cover_only_the_entry_and_exit_minutes_and_bars_the_middle() -> None:
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})

    read_series(server, target(Direction.SELL, OPEN_B, CLOSE_B, sl="1.08612"), at(11, 45))

    tick_windows = [(lo, hi) for sid, _kind, lo, hi in server.tick_requests if sid == EURUSD_ID]
    assert tick_windows
    for lo, hi in tick_windows:  # never a tick read across the 2 h in between
        assert lo >= ms(OPEN_B) - 1000  # whole seconds may be rounded outwards
        assert hi <= ms(MIDDLE_FROM) + 1000 or lo >= ms(MIDDLE_TO) - 1000
        assert hi <= ms(CLOSE_B) + 1000
    assert any(hi <= ms(MIDDLE_FROM) + 1000 for _lo, hi in tick_windows)
    assert any(lo >= ms(MIDDLE_TO) - 1000 for lo, _hi in tick_windows)
    ((symbol_id, period, lo, hi),) = server.trendbar_requests
    assert (symbol_id, period) == (EURUSD_ID, M1)
    assert lo == ms(MIDDLE_FROM)
    assert ms(MIDDLE_TO) - 60_000 <= hi <= ms(MIDDLE_TO)


def test_a_bar_overlapping_the_entry_or_exit_minute_is_never_used() -> None:
    decoys = [
        m1_bar(at(9, 0), "1.09500", "1.07500"),  # holds the entry second
        m1_bar(at(11, 30), "1.09500", "1.07500"),  # holds the exit second
        *BARS_SHORT,
    ]
    server = PhaseCServer(
        ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": decoys}, bars_ignore_range=True
    )

    series = read_series(server, target(Direction.SELL, OPEN_B, CLOSE_B, sl="1.08612"), at(11, 45))

    result = final_values(series, at(11, 45))
    assert (result.mfe_r, result.mae_r) == (D("1.8000"), D("0.7000"))


# --- series: incomplete / unavailable --------------------------------------------------------


@pytest.mark.parametrize(
    "rows",
    [
        [(at(9, 0, 40), "1.08502", "1.08512")],  # nothing in the exit minute
        [(CLOSE_B, "1.08410", "1.08430")],  # nothing in the entry minute
    ],
)
def test_no_tick_sample_at_entry_or_exit_makes_the_series_incomplete_then_unavailable(
    rows: list[tuple[datetime, str, str]],
) -> None:
    server = PhaseCServer(ticks={"EURUSD": quotes(*rows)}, bars={"EURUSD": BARS_SHORT})
    trade = target(Direction.SELL, OPEN_B, CLOSE_B, sl="1.08612")

    series = read_series(server, trade, at(11, 45))

    assert series.complete is False
    assert series.source is ExcursionSource.M1_TICKS
    assert evaluate(series, CLOSE_B + timedelta(minutes=20)) == ("retry", None)
    assert evaluate(series, CLOSE_B + UNAVAILABLE_AFTER) == ("retry", None)  # not yet: > 24 h
    after_a_day = CLOSE_B + UNAVAILABLE_AFTER + timedelta(minutes=1)
    assert evaluate(series, after_a_day) == ("unavailable", None)


def test_only_one_side_quoted_gives_no_tick_sample() -> None:
    only_bid = {BID: [(ms(at(9, 0, 40)), D("1.08502")), (ms(CLOSE_B), D("1.08410"))]}
    server = PhaseCServer(ticks={"EURUSD": only_bid}, bars={"EURUSD": BARS_SHORT})

    series = read_series(server, target(Direction.SELL, OPEN_B, CLOSE_B, sl="1.08612"), at(11, 45))

    assert series.complete is False
    assert evaluate(series, at(11, 45))[0] == "retry"


def test_no_ticks_at_all_for_a_short_trade_is_retry_then_unavailable() -> None:
    series = read_series(PhaseCServer(), target(Direction.BUY, OPEN_A, CLOSE_A), at(10, 40))

    assert series.samples == ()
    assert evaluate(series, CLOSE_A + timedelta(hours=1)) == ("retry", None)
    assert evaluate(series, CLOSE_A + timedelta(hours=25)) == ("unavailable", None)


# --- series: open trades ---------------------------------------------------------------------


def test_open_trade_gives_running_values_until_now() -> None:
    now = at(9, 30)
    rows = quotes(
        (at(9, 0), "1.08512", "1.08522"),
        (at(9, 10), "1.08662", "1.08672"),  # +1.5 R
        (at(9, 20), "1.08462", "1.08472"),  # 0.5 R against
        (at(9, 45), "1.09500", "1.09510"),  # after "now": must not count
    )
    server = PhaseCServer(ticks={"EURUSD": rows})

    series = read_series(server, target(Direction.BUY, OPEN_A, None), now)

    assert series.end_time == now
    assert series.source is ExcursionSource.TICKS
    outcome, result = evaluate(series, now)
    assert outcome == "running"
    assert result is not None
    assert (result.mfe_r, result.mae_r) == (D("1.5000"), D("0.5000"))


def test_open_trade_without_any_tick_is_retry_and_never_unavailable() -> None:
    series = read_series(PhaseCServer(), target(Direction.BUY, OPEN_A, None), at(9, 30))

    assert evaluate(series, at(9, 30)) == ("retry", None)
    assert evaluate(series, OPEN_A + timedelta(days=3)) == ("retry", None)


# --- failures and the time budget ------------------------------------------------------------


@pytest.mark.parametrize("failing", [2137, 2145])
def test_a_refused_request_raises_a_ctrader_error(failing: int) -> None:
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})
    server.handlers = _failing(server, {failing})  # type: ignore[method-assign]

    with pytest.raises(CtraderError):
        read_series(server, target(Direction.SELL, OPEN_B, CLOSE_B, sl="1.08612"), at(11, 45))


def _failing(server: PhaseCServer, kinds: set[int], symbol_id: int | None = None) -> Any:
    original = server.handlers

    def patched() -> Any:
        handlers = original()
        for kind in kinds:
            real = handlers[kind]

            def reply(frame: dict[str, Any], real: Any = real) -> Any:
                if symbol_id is not None and frame["payload"].get("symbolId") != symbol_id:
                    return real(frame)
                return 2142, {"errorCode": "INVALID_REQUEST", "description": "synthetic"}

            handlers[kind] = reply
        return handlers

    return patched


def _two_targets() -> list[ExcursionTarget]:
    first = target(Direction.BUY, OPEN_A, CLOSE_A)
    second = ExcursionTarget(
        2, "XAUUSD", Direction.BUY, D("2000.00"), D("1990.00"), OPEN_A, CLOSE_A
    )
    return [first, second]


def _fetch(server: PhaseCServer, budget_s: float = BUDGET_S) -> Any:
    ids = {"EURUSD": EURUSD_ID, "XAUUSD": XAUUSD_ID}
    points = {"EURUSD": POINT, "XAUUSD": D("0.01")}
    return run_async(
        server,
        lambda c: fetch_ctrader_series(
            c, CTID, _two_targets(), ids, points, at(10, 40), budget_s=budget_s
        ),
    )


def test_budget_is_a_short_fixed_limit() -> None:
    assert 0 < BUDGET_S <= 20  # MT5 uses 20 s; the whole cTrader read has 45 s


def test_fetch_reads_every_target_and_records_none_as_failed() -> None:
    gold = quotes((OPEN_A, "2000.00", "2000.50"), (at(10), "2005.00", "2005.50"))
    server = PhaseCServer(ticks={"EURUSD": TICKS_A, "XAUUSD": gold})

    fetched = _fetch(server)

    assert [s.target.trade_id for s in fetched.series] == [1, 2]
    assert fetched.failed == []


def test_a_failed_target_is_recorded_and_the_next_one_is_still_read() -> None:
    gold = quotes((OPEN_A, "2000.00", "2000.50"), (at(10), "2005.00", "2005.50"))
    server = PhaseCServer(ticks={"EURUSD": TICKS_A, "XAUUSD": gold})
    server.handlers = _failing(server, {2145}, symbol_id=EURUSD_ID)  # type: ignore[method-assign]

    fetched = _fetch(server)

    assert fetched.failed == [1]
    assert [s.target.trade_id for s in fetched.series] == [2]


def test_fetch_with_no_time_sends_nothing() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})

    fetched = _fetch(server, budget_s=0)

    assert (fetched.series, fetched.failed) == ([], [])
    assert server.tick_requests == []
    assert server.trendbar_requests == []


def test_a_read_cut_off_by_the_budget_is_an_attempt_and_ends_the_step() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})
    original = server.handlers

    def hanging() -> Any:
        handlers = original()
        handlers[2145] = None  # the server never answers
        return handlers

    server.handlers = hanging  # type: ignore[method-assign]
    began = time.monotonic()

    fetched = _fetch(server, budget_s=0.3)

    assert time.monotonic() - began < 5  # far below the 15 s request timeout
    assert fetched.series == []
    assert fetched.failed == [1]  # the cut-off trade is retried later; the next one is untouched

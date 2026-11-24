"""Review fixes (python-reviewer 2026-11-24, MEDIUM 2 and 3): a partial (hasMore) tick answer
never yields a stale latest tick, and a quote never pairs BID and ASK ticks of different ages.
No network: a fake connection answers 2145 from a list of points per side."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.ctrader import market
from app.ctrader.history import ms_from_utc
from app.ctrader.ticks import ASK, BID, last_tick
from app.domain.fx import ConversionPair
from tests.ctrader_phase_c_fakes import encode_ticks

CTID = 7
NOW = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
D = Decimal


def ms(minutes_ago: float) -> int:
    return ms_from_utc(NOW - timedelta(minutes=minutes_ago))


class PagedTicks:
    """Answers 2145 with at most ``page`` ticks of the asked range; ``oldest_first`` keeps
    the oldest of them (the case the reviewer flagged), else the newest."""

    def __init__(
        self, points: dict[int, list[tuple[int, Decimal]]], page: int, oldest_first: bool
    ) -> None:
        self.points = points
        self.page = page
        self.oldest_first = oldest_first
        self.requests: list[tuple[int, int, int]] = []

    async def request(self, _type: int, payload: dict[str, Any], *_: Any, **__: Any) -> Any:
        kind, lo, hi = payload["type"], payload["fromTimestamp"], payload["toTimestamp"]
        self.requests.append((kind, lo, hi))
        inside = sorted(p for p in self.points.get(kind, []) if lo <= p[0] <= hi)
        part = inside[: self.page] if self.oldest_first else inside[-self.page :]
        return {
            "ctidTraderAccountId": CTID,
            "tickData": encode_ticks(part),
            "hasMore": len(inside) > len(part),
        }


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.mark.parametrize("oldest_first", [True, False])
def test_partial_answer_still_finds_the_latest_tick(oldest_first: bool) -> None:
    points = {BID: [(ms(50 - i), D("1.10000") + D(i) / 100000) for i in range(10)]}
    fake = PagedTicks(points, page=3, oldest_first=oldest_first)

    tick = run(last_tick(fake, CTID, 1, BID, ms(60), ms(0)))  # type: ignore[arg-type]

    assert tick is not None
    assert tick.time == NOW - timedelta(minutes=41)
    assert tick.price == D("1.10009")


def test_paging_is_bounded_and_warns_when_the_latest_tick_stays_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    points = {BID: [(ms(59) + i, D("1.1")) for i in range(100)]}
    fake = PagedTicks(points, page=1, oldest_first=True)

    with caplog.at_level(logging.WARNING):
        tick = run(last_tick(fake, CTID, 1, BID, ms(60), ms(0)))  # type: ignore[arg-type]

    assert tick is None
    assert len(fake.requests) <= 8
    assert "latest tick not found" in caplog.text


PAIR = ConversionPair("EURUSD", False, "ask")


def quote(points: dict[int, list[tuple[int, Decimal]]]) -> Any:
    fake = PagedTicks(points, page=1000, oldest_first=False)
    return run(market._quote(fake, CTID, ("EUR", "USD", PAIR), 1, NOW))  # type: ignore[arg-type]


def test_bid_and_ask_of_different_ages_give_no_quote(caplog: pytest.LogCaptureFixture) -> None:
    points = {BID: [(ms(5), D("1.10000"))], ASK: [(ms(2 * 24 * 60), D("1.10020"))]}

    with caplog.at_level(logging.WARNING):
        assert quote(points) is None

    assert "apart" in caplog.text


def test_bid_above_ask_gives_no_quote(caplog: pytest.LogCaptureFixture) -> None:
    points = {BID: [(ms(5), D("1.10030"))], ASK: [(ms(5), D("1.10020"))]}

    with caplog.at_level(logging.WARNING):
        assert quote(points) is None

    assert "BID above ASK" in caplog.text


def test_close_bid_and_ask_give_a_quote() -> None:
    points = {BID: [(ms(5), D("1.10000"))], ASK: [(ms(4), D("1.10020"))]}

    got = quote(points)

    assert got is not None
    assert (got.bid, got.ask, got.at) == (D("1.10000"), D("1.10020"), NOW - timedelta(minutes=4))

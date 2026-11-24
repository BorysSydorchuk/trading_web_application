"""cTrader c5 wiring without a database: the reader's MAE/MFE step and hasMore paging.

Fake server only (`PhaseCServer`), synthetic numbers (see tests/test_ctrader_excursions.py).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app.ctrader import protocol as p
from app.ctrader.excursions import ExcursionRequest
from app.ctrader.history import HistoryRequest
from app.ctrader.reader import BalanceRead, Credentials, read_balances
from app.models.enums import Direction, ExcursionSource
from app.services.excursions import ExcursionTarget, evaluate
from tests.ctrader_fakes import ACCESS_TOKEN, CLIENT_ID, CLIENT_SECRET, CTID, no_sleep
from tests.ctrader_history_fakes import load
from tests.ctrader_phase_c_fakes import TICK_DATA_REQ, TRENDBARS_REQ, PhaseCServer
from tests.test_ctrader_excursions import (
    CLOSE_A,
    EURUSD_ID,
    OPEN_A,
    POINT,
    TICKS_A,
    at,
    read_series,
    target,
)

D = Decimal
NOW = at(10, 40)
ERROR_REPLY = (p.ERROR_RES, {"errorCode": "INVALID_REQUEST", "description": "synthetic"})


def _read(
    server: PhaseCServer,
    trades: tuple[ExcursionTarget, ...],
    *,
    history: bool = False,
    points: dict[str, Decimal] | None = None,
) -> BalanceRead:
    transport = server.transport()

    async def connector(_url: str) -> Any:
        return transport

    creds = Credentials(CLIENT_ID, SecretStr(CLIENT_SECRET), SecretStr(ACCESS_TOKEN))
    request = HistoryRequest(window_from=at(8), to=NOW)
    result = asyncio.run(
        read_balances(
            creds,
            [(CTID, False)],
            connector,
            sleep=no_sleep,
            history={CTID: request} if history else None,
            clock=lambda: NOW,
            excursions={CTID: ExcursionRequest(trades, points or {})},
        )
    )[CTID]
    assert isinstance(result, BalanceRead)
    return result


def _patch(server: PhaseCServer, kind: int, reply: Any) -> None:
    original = server.handlers

    def handlers() -> Any:
        found = original()
        found[kind] = reply(found[kind]) if callable(reply) else reply
        return found

    server.handlers = handlers  # type: ignore[method-assign]


LONG = target(Direction.BUY, OPEN_A, CLOSE_A)


def test_reader_measures_a_traded_symbol_with_the_point_from_its_digits() -> None:
    server = PhaseCServer(load("closed_simple.json")["deals"], ticks={"EURUSD": TICKS_A})

    read = _read(server, (LONG,), history=True)

    assert read.excursions is not None
    (series,) = read.excursions.series
    assert (series.point, series.source) == (D("0.00001"), ExcursionSource.TICKS)
    outcome, result = evaluate(series, NOW)
    assert outcome == "final"
    assert result is not None
    assert (result.mfe_r, result.mae_r) == (D("2.5000"), D("0.5000"))
    assert set(server.requests) >= {p.TICK_DATA_REQ, p.DEAL_LIST_REQ}


def test_a_symbol_outside_the_read_is_listed_once_and_uses_the_stored_point() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})

    read = _read(server, (LONG,), points={"EURUSD": POINT})

    assert read.excursions is not None
    (series,) = read.excursions.series
    assert series.point == POINT
    assert server.count(p.SYMBOLS_LIST_REQ) == 1
    assert {sid for sid, *_rest in server.tick_requests} == {EURUSD_ID}


def test_an_unknown_symbol_is_a_failed_attempt_without_a_price_request() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})
    unknown = ExcursionTarget(5, "NOPE", Direction.BUY, D("1"), D("0.9"), OPEN_A, CLOSE_A)

    read = _read(server, (unknown,))

    assert read.excursions is not None
    assert (read.excursions.series, read.excursions.failed) == ([], [5])
    assert server.tick_requests == []


def test_no_time_left_sends_no_price_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ctrader.excursions.BUDGET_S", 0.0)
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})

    read = _read(server, (LONG,))

    assert read.excursions is None
    assert not {TICK_DATA_REQ, TRENDBARS_REQ} & set(server.requests)
    assert read.balance == D("1000.50")


def test_no_targets_sends_nothing() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})

    read = _read(server, ())

    assert read.excursions is None
    assert server.tick_requests == []


def test_a_refused_price_request_keeps_the_balance_and_records_an_attempt() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})
    _patch(server, TICK_DATA_REQ, ERROR_REPLY)

    read = _read(server, (LONG,))

    assert (read.balance, read.equity) == (D("1000.50"), D("1000.50"))
    assert read.excursions is not None
    assert (read.excursions.series, read.excursions.failed) == ([], [1])


# --- hasMore paging ---------------------------------------------------------------------------


def _at_most(rows: int) -> Any:
    """Wrap the 2145 handler: an answer with more than ``rows`` ticks keeps its first ``rows``
    (a valid delta prefix) and says hasMore."""

    def wrap(real: Any) -> Any:
        def reply(frame: dict[str, Any]) -> Any:
            kind, payload = real(frame)
            ticks = payload["tickData"]
            if len(ticks) > rows:
                payload = {**payload, "tickData": ticks[:rows], "hasMore": True}
            return kind, payload

        return reply

    return wrap


def test_a_has_more_tick_answer_is_split_until_every_tick_is_read() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})
    _patch(server, TICK_DATA_REQ, _at_most(2))

    series = read_series(server, LONG, NOW)

    assert len(series.samples) == 5
    assert series.complete is True
    outcome, result = evaluate(series, NOW)
    assert outcome == "final"
    assert result is not None
    assert (result.mfe_r, result.mae_r) == (D("2.5000"), D("0.5000"))


def test_ticks_that_never_fit_make_the_series_incomplete() -> None:
    server = PhaseCServer(ticks={"EURUSD": TICKS_A})
    _patch(server, TICK_DATA_REQ, _at_most(0))

    series = read_series(server, LONG, NOW)

    assert series.complete is False
    assert evaluate(series, NOW) == ("retry", None)
    assert evaluate(series, CLOSE_A + timedelta(hours=25)) == ("unavailable", None)
    assert len(server.tick_requests) <= 16  # one side, at most MAX_PAGES requests

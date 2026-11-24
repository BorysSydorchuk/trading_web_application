"""cTrader phase c, c5 through the worker job: MAE / MFE of cTrader trades.

Fake server and DB only (`PhaseCServer` with 2145 ticks and 2137 M1 trendbars), no live call, all
numbers synthetic (see the assumptions in tests/test_ctrader_excursions.py). The same rules as
MT5 M8-16: closed trades of the last 7 days are measured at most every 10 minutes until final,
only a trade closed more than 24 h ago becomes ``unavailable``, an open trade has a running value.

A trade is seeded the way production sees it: the cycle after the open creates it, the cycle
after the close closes it (both without price data, so no value yet), the measuring cycle
comes `MEASURE_AFTER` after the close. Targets are chosen before the read, so a trade is first
measured in the cycle after the one that stored it.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.ctrader import guard
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import Account, Trade
from app.models.enums import Direction, ExcursionSource, ExcursionStatus
from app.services.excursions import RETRY_EVERY, excursion_targets
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    make_ctrader_account,
    make_mt5_account,
)
from tests.ctrader_history_fakes import load
from tests.ctrader_phase_c_fakes import PhaseCServer
from tests.test_ctrader_excursions import (
    BARS_SHORT,
    CLOSE_A,
    CLOSE_B,
    EDGE_TICKS_SHORT,
    OPEN_A,
    OPEN_B,
    TICKS_A,
    at,
    ms,
    quotes,
)
from tests.test_ctrader_phase_c_job import NOW, last_log, run, trade_of

D = Decimal
MEASURE_AFTER = timedelta(minutes=20)
PID_LONG, PID_SHORT = 6001, 6002


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


@pytest.fixture
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    token_store = TokenStore(tokens_path(tmp_path))
    token_store.write(
        TokenPair(SecretStr(ACCESS_TOKEN), SecretStr(REFRESH_TOKEN), NOW + timedelta(days=30), NOW)
    )
    return token_store


@pytest.fixture
def account(session: Session) -> Account:
    return make_ctrader_account(session, reference_balance=D("1000.00"))


@dataclass(frozen=True)
class Deals:
    entry: dict[str, Any]
    exit: dict[str, Any]
    position: dict[str, Any]
    pnl: dict[str, Any]


def make_deals(
    pid: int,
    side: str,
    open_at: datetime,
    close_at: datetime,
    entry: str,
    exit_: str,
    sl: str | None,
) -> Deals:
    """EURUSD 0.10 lot built from tests/fixtures/ctrader/closed_simple.json."""
    base = load("closed_simple.json")
    opening, closing = copy.deepcopy(base["deals"])
    position = copy.deepcopy(base["open_position"])
    pnl = copy.deepcopy(base["open_pnl"])
    closing_side = "SELL" if side == "BUY" else "BUY"
    for deal, when, price, deal_side, suffix in (
        (opening, open_at, entry, side, 1),
        (closing, close_at, exit_, closing_side, 2),
    ):
        deal.update(
            dealId=pid * 10 + suffix,
            orderId=pid * 10 + suffix,
            positionId=pid,
            executionTimestamp=ms(when),
            createTimestamp=ms(when) - 120,
            utcLastUpdateTimestamp=ms(when),
            executionPrice=float(price),
            tradeSide=deal_side,
        )
    closing["closePositionDetail"]["entryPrice"] = float(entry)
    position.update(positionId=pid, price=float(entry), utcLastUpdateTimestamp=ms(open_at))
    position["tradeData"].update(tradeSide=side, openTimestamp=ms(open_at))
    if sl is not None:
        position["stopLoss"] = float(sl)
    else:
        position.pop("stopLoss", None)
    position.pop("takeProfit", None)
    pnl["positionId"] = pid
    return Deals(opening, closing, position, pnl)


LONG = make_deals(PID_LONG, "BUY", OPEN_A, CLOSE_A, "1.08512", "1.08712", "1.08412")
LONG_NO_SL = make_deals(PID_LONG, "BUY", OPEN_A, CLOSE_A, "1.08512", "1.08712", None)
SHORT = make_deals(PID_SHORT, "SELL", OPEN_B, CLOSE_B, "1.08512", "1.08410", "1.08612")


def seed(
    factory: sessionmaker[Session],
    store: TokenStore,
    tmp_path: Path,
    deals: Deals,
    close_at: datetime,
) -> None:
    """The trade open (cycle 1) and then closed (cycle 2), both without price data."""
    opened = datetime.fromtimestamp(deals.entry["executionTimestamp"] / 1000, UTC)
    first = PhaseCServer([deals.entry], [deals.position], [deals.pnl])
    run(factory, store, first, tmp_path, opened + timedelta(minutes=5))
    second = PhaseCServer([deals.entry, deals.exit])
    run(factory, store, second, tmp_path, close_at + timedelta(minutes=1))


def measure(
    factory: sessionmaker[Session],
    store: TokenStore,
    tmp_path: Path,
    deals: Deals,
    server: PhaseCServer,
    when: datetime,
) -> None:
    server.deals = [deals.entry, deals.exit]
    run(factory, store, server, tmp_path, when)


def patched(server: PhaseCServer, replies: dict[int, Any]) -> None:
    """Replace handlers of ``server`` (a reply tuple, or None for a request never answered)."""
    original = server.handlers

    def handlers() -> Any:
        result = original()
        result.update(replies)
        return result

    server.handlers = handlers  # type: ignore[method-assign]


ERROR_REPLY = (2142, {"errorCode": "INVALID_REQUEST", "description": "synthetic"})


# --- finals ---------------------------------------------------------------------------------


def test_closed_long_under_two_hours_is_final_from_ticks(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, LONG, CLOSE_A)
    measured_at = CLOSE_A + MEASURE_AFTER

    measure(factory, store, tmp_path, LONG, PhaseCServer(ticks={"EURUSD": TICKS_A}), measured_at)

    trade = trade_of(session, PID_LONG, account)
    assert trade.initial_sl == D("1.08412")
    assert (trade.excursion_status, trade.excursion_source) == (
        ExcursionStatus.FINAL.value,
        ExcursionSource.TICKS.value,
    )
    assert trade.excursion_at == measured_at
    assert (trade.mfe_price, trade.mfe_time) == (D("1.08762"), at(9, 40))
    assert (trade.mfe_r, trade.mfe_points) == (D("2.5000"), D("250.0"))
    assert (trade.mae_price, trade.mae_time) == (D("1.08462"), at(9, 10))
    assert (trade.mae_r, trade.mae_points) == (D("0.5000"), D("50.0"))


def test_closed_short_over_two_hours_uses_bars_with_the_median_spread(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, SHORT, CLOSE_B)
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})

    measure(factory, store, tmp_path, SHORT, server, CLOSE_B + MEASURE_AFTER)

    trade = trade_of(session, PID_SHORT, account)
    assert (trade.excursion_status, trade.excursion_source) == (
        ExcursionStatus.FINAL.value,
        ExcursionSource.M1_TICKS.value,
    )
    # median ASK-BID of the entry/exit ticks = 0.0002; short measured on ASK (bar bid + 0.0002)
    assert (trade.mfe_price, trade.mfe_r, trade.mfe_points) == (
        D("1.08332"),
        D("1.8000"),
        D("180.0"),
    )
    assert trade.mae_price == D("1.08582")
    assert (trade.mae_r, trade.mae_points) == (D("0.7000"), D("70.0"))
    assert (trade.mfe_time, trade.mae_time) == (at(10, 15), at(10, 45))
    assert [r for r in server.trendbar_requests if r[0] == 1]  # EURUSD bars were asked for


def test_missing_initial_sl_stores_points_and_no_r(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, LONG_NO_SL, CLOSE_A)

    measure(
        factory,
        store,
        tmp_path,
        LONG_NO_SL,
        PhaseCServer(ticks={"EURUSD": TICKS_A}),
        CLOSE_A + MEASURE_AFTER,
    )

    trade = trade_of(session, PID_LONG, account)
    assert trade.initial_sl is None
    assert trade.excursion_status == ExcursionStatus.FINAL.value
    assert (trade.mfe_r, trade.mae_r) == (None, None)
    assert (trade.mfe_points, trade.mae_points) == (D("250.0"), D("50.0"))


def test_a_final_trade_is_not_measured_again(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, LONG, CLOSE_A)
    measure(
        factory, store, tmp_path, LONG, PhaseCServer(ticks={"EURUSD": TICKS_A}),
        CLOSE_A + MEASURE_AFTER,
    )  # fmt: skip
    later = PhaseCServer()  # no price data at all: a re-measure would wipe or retry the trade

    measure(factory, store, tmp_path, LONG, later, CLOSE_A + timedelta(hours=1))

    trade = trade_of(session, PID_LONG, account)
    assert (trade.excursion_status, trade.mfe_r) == (ExcursionStatus.FINAL.value, D("2.5000"))
    assert trade.excursion_at == CLOSE_A + MEASURE_AFTER  # no new attempt
    assert later.trendbar_requests == []


def test_same_targets_as_mt5(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, LONG, CLOSE_A)
    now = CLOSE_A + MEASURE_AFTER

    due = excursion_targets(session, account.id, now)
    assert [(t.broker_symbol, t.initial_sl, t.close_time) for t in due] == [
        ("EURUSD", D("1.08412"), CLOSE_A)
    ]

    measure(factory, store, tmp_path, LONG, PhaseCServer(ticks={"EURUSD": TICKS_A}), now)
    session.expire_all()
    assert excursion_targets(session, account.id, now + RETRY_EVERY * 2) == []


# --- retry, unavailable, running ------------------------------------------------------------


def test_incomplete_history_is_retried_then_unavailable_after_a_day(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, SHORT, CLOSE_B)
    entry_only = quotes((at(9, 0, 40), "1.08502", "1.08512"))  # nothing in the exit minute
    server = PhaseCServer(ticks={"EURUSD": entry_only}, bars={"EURUSD": BARS_SHORT})
    soon = CLOSE_B + MEASURE_AFTER

    measure(factory, store, tmp_path, SHORT, server, soon)

    trade = trade_of(session, PID_SHORT, account)
    assert (trade.excursion_status, trade.mfe_r, trade.mae_r) == (None, None, None)
    assert trade.excursion_at == soon  # an attempt: retried after RETRY_EVERY

    after_a_day = CLOSE_B + timedelta(hours=24, minutes=5)
    measure(factory, store, tmp_path, SHORT, server, after_a_day)

    trade = trade_of(session, PID_SHORT, account)
    assert trade.excursion_status == ExcursionStatus.UNAVAILABLE.value
    assert (trade.mfe_r, trade.mfe_price) == (None, None)


def test_closed_trade_without_any_tick_is_retried_until_it_is_a_day_old(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, LONG, CLOSE_A)

    measure(factory, store, tmp_path, LONG, PhaseCServer(), CLOSE_A + MEASURE_AFTER)
    assert trade_of(session, PID_LONG, account).excursion_status is None

    measure(factory, store, tmp_path, LONG, PhaseCServer(), CLOSE_A + timedelta(hours=25))
    assert trade_of(session, PID_LONG, account).excursion_status == "unavailable"


def test_open_trade_has_running_values_that_refresh(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    opened = PhaseCServer([LONG.entry], [LONG.position], [LONG.pnl])
    run(factory, store, opened, tmp_path, at(9, 5))  # the trade is created, still open

    first = PhaseCServer([LONG.entry], [LONG.position], [LONG.pnl], ticks={"EURUSD": TICKS_A})
    run(factory, store, first, tmp_path, at(9, 30))
    trade = trade_of(session, PID_LONG, account)
    assert trade.close_time is None
    assert (trade.excursion_status, trade.excursion_source) == ("running", "ticks")
    # only what happened until 09:30: the 09:40 high is not known yet
    assert (trade.mfe_r, trade.mae_r) == (D("0.0000"), D("0.5000"))

    second = PhaseCServer([LONG.entry], [LONG.position], [LONG.pnl], ticks={"EURUSD": TICKS_A})
    run(factory, store, second, tmp_path, at(9, 45))
    trade = trade_of(session, PID_LONG, account)
    assert trade.excursion_status == "running"  # never final while open
    assert (trade.mfe_r, trade.mae_r) == (D("2.5000"), D("0.5000"))
    assert trade.excursion_at == at(9, 45)


# --- failures and the budget never fail the sync --------------------------------------------


@pytest.mark.parametrize(
    ("deals", "close_at", "failing", "data"),
    [
        (LONG, CLOSE_A, 2145, {"ticks": {"EURUSD": TICKS_A}}),
        (
            SHORT,
            CLOSE_B,
            2137,
            {"ticks": {"EURUSD": EDGE_TICKS_SHORT}, "bars": {"EURUSD": BARS_SHORT}},
        ),
    ],
)
def test_a_failed_price_request_records_an_attempt_and_never_fails_the_sync(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    deals: Deals,
    close_at: datetime,
    failing: int,
    data: dict[str, Any],
) -> None:
    seed(factory, store, tmp_path, deals, close_at)
    server = PhaseCServer(**data)
    patched(server, {failing: ERROR_REPLY})
    measured_at = close_at + MEASURE_AFTER

    measure(factory, store, tmp_path, deals, server, measured_at)

    pid = deals.entry["positionId"]
    trade = trade_of(session, pid, account)
    assert trade.excursion_at == measured_at  # recorded, retried after RETRY_EVERY
    assert (trade.excursion_status, trade.mfe_r, trade.mae_r) == (None, None, None)
    session.expire_all()
    stored = session.get(Account, account.id)
    assert stored is not None
    assert stored.balance == D("1000.50")
    log = last_log(session, account)
    assert (log.ok, log.error_code) == (True, None)
    assert trade.close_time == close_at  # the trade itself is stored


def test_the_excursion_step_stays_within_its_own_time_budget(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The reader must take the limit from `app.ctrader.excursions.BUDGET_S` when it runs (not
    # bind it at import), so this patch is what the job uses.
    monkeypatch.setattr("app.ctrader.excursions.BUDGET_S", 0.3)
    seed(factory, store, tmp_path, SHORT, CLOSE_B)
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})
    patched(server, {2137: None})  # the bars are never answered
    measured_at = CLOSE_B + MEASURE_AFTER

    began = time.monotonic()
    measure(factory, store, tmp_path, SHORT, server, measured_at)

    assert time.monotonic() - began < 8  # not the 15 s request timeout, nor the 45 s read
    trade = trade_of(session, PID_SHORT, account)
    assert trade.excursion_status is None
    assert trade.excursion_at == measured_at  # the cut-off trade counts as an attempt
    session.expire_all()
    stored = session.get(Account, account.id)
    assert stored is not None
    assert stored.balance == D("1000.50")
    assert last_log(session, account).ok is True


def test_no_time_left_sends_no_trendbar_request_and_keeps_the_trade_for_later(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ctrader.excursions.BUDGET_S", 0.0)
    seed(factory, store, tmp_path, SHORT, CLOSE_B)
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})
    measured_at = CLOSE_B + MEASURE_AFTER

    measure(factory, store, tmp_path, SHORT, server, measured_at)

    assert server.trendbar_requests == []
    trade = trade_of(session, PID_SHORT, account)
    assert trade.excursion_status is None
    assert trade.excursion_at != measured_at  # untouched: not even an attempt
    assert last_log(session, account).ok is True


# --- MT5 untouched, read-only guard ---------------------------------------------------------


def test_mt5_excursions_are_untouched_by_the_ctrader_cycle(
    session: Session,
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    mt5 = make_mt5_account(session)
    common: dict[str, Any] = {
        "account_id": mt5.id,
        "symbol": "EURUSD",
        "direction": Direction.BUY,
        "open_time": OPEN_A,
        "close_time": CLOSE_A,
        "entry_price": D("1.08512"),
        "volume": D("0.10"),
    }
    session.add_all(
        [
            Trade(position_id=71, **common),  # waiting for MT5 history: stays waiting
            Trade(
                position_id=72,
                excursion_status="final",
                excursion_source="ticks",
                mfe_r=D("9.1234"),
                mae_r=D("0.1000"),
                mfe_price=D("1.09000"),
                excursion_at=OPEN_A,
                **common,
            ),
        ]
    )
    session.commit()
    seed(factory, store, tmp_path, LONG, CLOSE_A)

    measure(
        factory, store, tmp_path, LONG, PhaseCServer(ticks={"EURUSD": TICKS_A}),
        CLOSE_A + MEASURE_AFTER,
    )  # fmt: skip

    session.expire_all()
    waiting, done = (
        session.scalars(select(Trade).where(Trade.account_id == mt5.id).order_by(Trade.position_id))
    ).all()
    assert (waiting.excursion_status, waiting.excursion_at, waiting.mfe_r) == (None, None, None)
    assert (done.excursion_status, done.mfe_r, done.mae_r, done.mfe_price) == (
        "final",
        D("9.1234"),
        D("0.1000"),
        D("1.09000"),
    )
    assert done.excursion_at == OPEN_A
    assert trade_of(session, PID_LONG, account).excursion_status == "final"  # cTrader's own
    assert {t.trade_id for t in excursion_targets(session, mt5.id, CLOSE_A + MEASURE_AFTER)} == {
        waiting.id
    }


def test_only_read_only_messages_are_sent_and_the_allowlist_is_unchanged(
    factory: sessionmaker[Session],
    store: TokenStore,
    account: Account,
    tmp_path: Path,
) -> None:
    seed(factory, store, tmp_path, SHORT, CLOSE_B)
    server = PhaseCServer(ticks={"EURUSD": EDGE_TICKS_SHORT}, bars={"EURUSD": BARS_SHORT})

    measure(factory, store, tmp_path, SHORT, server, CLOSE_B + MEASURE_AFTER)

    pinned = frozenset({51, 2100, 2102, 2112, 2114, 2116, 2121, 2124, 2133, 2137, 2145, 2149, 2187})
    assert pinned == guard.ALLOWED_OUTGOING
    assert {2137, 2145} <= set(server.requests)  # both used by this step
    assert set(server.requests) <= guard.ALLOWED_OUTGOING
    assert server.count(2137) >= 1

"""Open-trade reconciliation (owner bug 2026-11-20): a trade the DB has open whose position
MT5 no longer reports is closed from its own deal history, however old the close is; a
freshly started terminal that answers with empty lists is read again; if the history never
shows the close, the trade stays open and is reported as unconfirmed (retried next sync)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import Account, SyncLog
from app.mt5.types import RawDeal, RawPosition
from app.services import sync as sync_service
from app.services.sync import sync_account
from tests.test_sync import (
    SYMBOLS,
    WEEK_LOGIN,
    WEEK_NOW,
    WEEK_STEP1_NOW,
    Wrapped,
    add_account,
    password,
    source,
    trades_by_pid,
)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    db = make_session_factory(db_engine)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def rules() -> RulesConfig:
    return get_rules()


T7 = 2000701  # basic_week: open at step 0, closed 2026-10-23 13:30 UTC at step 1


class Terminal(Wrapped):
    """basic_week source whose history/positions read empty while ``cold`` (a terminal the
    worker just started); ``never_loads``: the position history of ``T7`` never arrives."""

    def __init__(self, *, cold: bool = False, never_loads: bool = False) -> None:
        super().__init__(source("basic_week.json"))
        self.cold = cold
        self.never_loads = never_loads

    def deals(self, from_server_epoch: int, to_server_epoch: int) -> list[RawDeal]:
        return [] if self.cold else super().deals(from_server_epoch, to_server_epoch)

    def open_positions(self) -> list[RawPosition]:
        return [] if self.cold else super().open_positions()

    def deals_for_position(self, position_id: int) -> list[RawDeal]:
        if self.cold or (self.never_loads and position_id == T7):
            return []
        return super().deals_for_position(position_id)


def no_overlap(rules: RulesConfig) -> RulesConfig:
    """Window = from the last successful sync exactly (no 3-day re-read)."""
    return rules.model_copy(update={"sync": rules.sync.model_copy(update={"overlap_days": 0})})


def _open_then_close_elsewhere(session: Session, src: Terminal, rules: RulesConfig) -> int:
    """T7 synced open, journal written; then it closes while this DB is not synced, and a
    later successful sync (e.g. while .env pointed at another DB) moves the window past the
    close. Returns the account id."""
    account = add_account(session, WEEK_LOGIN)
    first = sync_account(session, account, src, rules, WEEK_NOW, password_for=password,
                         symbols=SYMBOLS)  # fmt: skip
    assert first.ok is True, first.error_message
    t7 = trades_by_pid(session, account.id)[T7]
    assert t7.status == "open"
    t7.lesson = "my note"
    session.add(SyncLog(account_id=account.id, started_at=WEEK_STEP1_NOW, ok=True))
    session.commit()
    src.base.advance()  # MT5: T7 closed at 13:30, before the window start (13:31)
    return account.id


def _sync(session: Session, src: Terminal, rules: RulesConfig, pauses: list[float]) -> SyncLog:
    account = session.get(Account, 1)
    assert account is not None
    return sync_account(
        session,
        account,
        src,
        rules,
        WEEK_STEP1_NOW + timedelta(minutes=15),
        password_for=password,
        symbols=SYMBOLS,
        pause=pauses.append,
    )


def test_closed_while_away_is_closed_from_position_history(
    session: Session, rules: RulesConfig
) -> None:
    rules = no_overlap(rules)
    src = Terminal()
    account_id = _open_then_close_elsewhere(session, src, rules)
    pauses: list[float] = []
    log = _sync(session, src, rules, pauses)
    assert log.ok is True, log.error_message
    assert pauses == []
    t7 = trades_by_pid(session, account_id)[T7]
    assert t7.close_time is not None
    assert t7.close_time == datetime(2026, 10, 23, 13, 30, tzinfo=UTC)
    assert t7.net_pnl == Decimal("235.20")
    assert t7.status == "needs_description"
    assert t7.lesson == "my note"  # the journal survives the close


def test_cold_terminal_skips_the_cycle_then_the_next_sync_closes_the_trade(
    session: Session, rules: RulesConfig
) -> None:
    """Readiness gate: empty first read, real deals on the second -> «термінал ще
    завантажується» for this cycle (no cursor moves); the next sync loses nothing."""
    rules = no_overlap(rules)
    src = Terminal()
    account_id = _open_then_close_elsewhere(session, src, rules)
    window_before = sync_service.history_window_start(
        session, account_id, rules.sync, WEEK_STEP1_NOW + timedelta(minutes=15)
    )
    src.cold = True
    pauses: list[float] = []

    def warm_up(seconds: float) -> None:
        pauses.append(seconds)
        src.cold = False

    account = session.get(Account, account_id)
    assert account is not None
    at = WEEK_STEP1_NOW + timedelta(minutes=15)
    log = sync_account(
        session, account, src, rules, at, password_for=password, symbols=SYMBOLS, pause=warm_up
    )
    assert (log.ok, log.error_code) == (False, "terminal_loading")
    assert pauses == [sync_service.READY_PAUSE_S]
    assert trades_by_pid(session, account_id)[T7].close_time is None  # nothing written
    later = at + timedelta(minutes=1)
    assert sync_service.history_window_start(session, account_id, rules.sync, later) == (
        window_before
    )  # the failed attempt did not move the cursor
    assert sync_service.is_due(session, account_id, rules, later)  # retried next cycle

    log = sync_account(
        session, account, src, rules, later, password_for=password, symbols=SYMBOLS,
        pause=pauses.append,
    )  # fmt: skip
    assert log.ok is True, log.error_message
    assert trades_by_pid(session, account_id)[T7].close_time is not None


def test_empty_history_while_the_journal_has_trades_in_the_window_is_loading(
    session: Session, rules: RulesConfig
) -> None:
    """Both reads empty and consistent, but trades of this window are in the journal."""
    src = Terminal()
    account = add_account(session, WEEK_LOGIN)
    first = sync_account(
        session, account, src, rules, WEEK_NOW, password_for=password, symbols=SYMBOLS
    )
    assert first.ok is True, first.error_message
    before = len(trades_by_pid(session, account.id))
    src.cold = True  # never warms up
    pauses: list[float] = []
    log = sync_account(
        session, account, src, rules, WEEK_NOW + timedelta(minutes=1), password_for=password,
        symbols=SYMBOLS, pause=pauses.append,
    )  # fmt: skip
    assert (log.ok, log.error_code) == (False, "terminal_loading")
    assert log.error_message is not None
    assert "journal has trades" in log.error_message
    assert len(trades_by_pid(session, account.id)) == before


def test_terminal_not_connected_is_loading(session: Session, rules: RulesConfig) -> None:
    src = Terminal()
    account = add_account(session, WEEK_LOGIN)
    src.terminal_connected = lambda: False  # type: ignore[method-assign]
    log = sync_account(
        session, account, src, rules, WEEK_NOW, password_for=password, symbols=SYMBOLS
    )
    assert (log.ok, log.error_code) == (False, "terminal_loading")
    assert trades_by_pid(session, account.id) == {}


def test_warm_terminal_without_the_history_does_not_wait(
    session: Session, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    """History purged / other server: nothing to wait for on every sync; unconfirmed only."""
    rules = no_overlap(rules)
    src = Terminal(never_loads=True)
    account_id = _open_then_close_elsewhere(session, src, rules)
    # Warm terminal: the window has a deal (a balance credit after the window start).
    src.extra_deals = [
        RawDeal(
            ticket=1999990, order=0, position_id=0, type=2, entry=0, volume=Decimal("0"),
            time=int(datetime(2026, 10, 23, 16, 40, tzinfo=UTC).timestamp()),  # server wall
            price=Decimal("0"), profit=Decimal("1"), symbol="",
        )
    ]  # fmt: skip
    pauses: list[float] = []
    log = _sync(session, src, rules, pauses)
    assert log.ok is True, log.error_message  # retried next sync, not a failed sync
    assert pauses == []
    t7 = trades_by_pid(session, account_id)[T7]
    assert (t7.close_time, t7.status, t7.lesson) == (None, "open", "my note")
    assert "not reported by MT5" in caplog.text
    assert str(T7) in caplog.text


def test_terminal_that_stays_cold_is_retried_a_bounded_number_of_times(
    session: Session, rules: RulesConfig
) -> None:
    rules = no_overlap(rules)
    src = Terminal()
    account_id = _open_then_close_elsewhere(session, src, rules)
    src.cold = True  # never warms up
    pauses: list[float] = []
    log = _sync(session, src, rules, pauses)
    assert log.ok is True, log.error_message  # nothing in the window and nothing expected
    # one readiness pause, then the bounded re-reads for the missing open position
    assert len(pauses) == 1 + sync_service.HISTORY_READ_ATTEMPTS - 1
    assert trades_by_pid(session, account_id)[T7].close_time is None  # retried next sync


ENTRY = RawDeal(
    ticket=1999901, order=2999901, position_id=2999901, time=1_792_000_000, type=0, entry=0,
    volume=Decimal("0.10"), price=Decimal("1.16000"), profit=Decimal("0"), symbol="EURUSD",
)  # fmt: skip
PARTIAL_EXIT = RawDeal(
    ticket=1999902, order=2999902, position_id=2999901, time=1_792_000_600, type=1, entry=1,
    volume=Decimal("0.05"), price=Decimal("1.16100"), profit=Decimal("5"), symbol="EURUSD",
)  # fmt: skip


@pytest.mark.parametrize(
    ("deals", "expected"),
    [((ENTRY,), {2999901}), ((ENTRY, PARTIAL_EXIT), {2999901})],
    ids=["entry-only", "partial-close"],
)
def test_partly_or_not_closed_history_is_unconfirmed(
    deals: tuple[RawDeal, ...], expected: set[int]
) -> None:
    src = Wrapped(source("basic_week.json"), deals=list(deals))
    src.connect("x", WEEK_LOGIN, password(0), "FundedNext-Server")
    pauses: list[float] = []
    try:
        read = sync_service.read_trading(src, 0, 2**31, {2999901}, pause=pauses.append)
    finally:
        src.shutdown()
    assert read.unconfirmed == frozenset(expected)
    assert 2999901 in read.pids  # built (still open), not dropped
    assert pauses == []  # warm terminal: no waiting


def test_read_trading_reports_unconfirmed_and_keeps_live_positions() -> None:
    src = Terminal(never_loads=True)
    src.connect("x", WEEK_LOGIN, password(0), "FundedNext-Server")
    try:
        read = sync_service.read_trading(src, 0, 2**31, {T7, 4242}, pause=lambda _s: None)
    finally:
        src.shutdown()
    assert read.unconfirmed == frozenset({4242})  # T7 is still a live position at step 0
    assert T7 in {p.identifier for p in read.positions}  # step 0: still open in MT5 ...
    assert T7 in read.pids  # ... so it is built as an open position as before
    assert 4242 not in read.pids  # no deal at all: nothing to build

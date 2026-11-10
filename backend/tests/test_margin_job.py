"""The calculator margin worker job (docs/api.md "Margin integration design", M5-04d).

`run_margin_cycle(session_factory, source, lock, *, password_for=...)` handles at most one
pending request per run (oldest first, FOR UPDATE SKIP LOCKED) under the lock shared with
sync (non-blocking acquire), after expiring pending rows past `expires_at`. Fixture MT5
sources only; never a real terminal. All margin values are SYNTHETIC.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import Account
from app.models.calculator import CalculatorMarginRequest
from app.models.enums import AccountPhase
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from app.mt5.types import RawAccountInfo
from app.services.margin_requests import STALE_PROCESSING_S
from app.worker import margin_job
from app.worker.margin_job import (
    INTERRUPTED,
    REQUEST_EXPIRED,
    finish,
    mark_interrupted_margin_requests,
    run_margin_cycle,
)
from app.worker.sync_job import run_sync_cycle

D = Decimal
LOGIN = 51234567
SERVER = "FundedNext-Server"
TERMINAL = "D:\\MT5\\fn\\terminal64.exe"
ACCOUNT_JSON = {
    "login": LOGIN,
    "server": SERVER,
    "balance": "10000.00",
    "equity": "10000.00",
    "currency": "USD",
}
MARGINS = {"EURUSD": {"buy": "1100.00", "sell": "1099.50"}}


def password(_: int) -> SecretStr:
    return SecretStr("not-a-real-secret")


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
def lock() -> threading.Lock:
    return threading.Lock()


class RecordingSource(FixtureMt5Source):
    """Fixture source that records calc_margin arguments and the lock state at connect."""

    def __init__(self, data: dict[str, Any], lock: threading.Lock | None = None) -> None:
        super().__init__(data)
        self.margin_args: list[tuple[str, str, Decimal, Decimal]] = []
        self.lock_held_at_connect: list[bool] = []
        self._watched_lock = lock

    def connect(self, *args: Any, **kwargs: Any) -> RawAccountInfo:
        if self._watched_lock is not None:
            self.lock_held_at_connect.append(self._watched_lock.locked())
        return super().connect(*args, **kwargs)

    def calc_margin(self, direction: Any, symbol: str, volume: Decimal, price: Decimal) -> Decimal:
        self.margin_args.append((direction, symbol, volume, price))
        return super().calc_margin(direction, symbol, volume, price)


def fixture_source(lock: threading.Lock | None = None, **changes: Any) -> RecordingSource:
    data: dict[str, Any] = {"format": 1, "account": ACCOUNT_JSON, "margins": MARGINS}
    return RecordingSource(data | changes, lock)


def add_account(session: Session, login: int = LOGIN, **kw: Any) -> Account:
    values: dict[str, Any] = {
        "name": f"FN {login}",
        "firm": "FundedNext",
        "program": "Stellar 2-Step",
        "phase": AccountPhase.PHASE_1.value,
        "login": login,
        "server": SERVER,
        "terminal_path": TERMINAL,
        "starting_balance": D("10000.00"),
        "currency": "USD",
    }
    account = Account(**(values | kw))
    session.add(account)
    session.commit()
    return account


def add_request(
    session: Session,
    account: Account,
    *,
    age_s: float = 0,
    ttl_s: float = 60,
    **changes: Any,
) -> int:
    """A request created ``age_s`` seconds ago (DB clock) that expires ``ttl_s`` after it."""
    created = func.now() - timedelta(seconds=age_s)
    values: dict[str, Any] = {
        "account_id": account.id,
        "symbol": "EURUSD",
        "direction": "buy",
        "volume": D("0.50"),
        "entry": D("1.10000"),
        "currency": "USD",
        "created_at": created,
        "expires_at": created + timedelta(seconds=ttl_s),
    }
    row = CalculatorMarginRequest(**(values | changes))
    session.add(row)
    session.commit()
    return row.id


def load(session: Session, request_id: int) -> CalculatorMarginRequest:
    session.expire_all()
    row = session.get(CalculatorMarginRequest, request_id)
    assert row is not None
    return row


def db_now(db_engine: Engine) -> datetime:
    with db_engine.connect() as conn:
        value = conn.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def run(
    factory: sessionmaker[Session], source: FixtureMt5Source, lock: threading.Lock, **kw: Any
) -> int | None:
    kw.setdefault("password_for", password)
    return run_margin_cycle(factory, source, lock, **kw)


# --- happy path ---


def test_no_pending_request_does_nothing_and_never_connects(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    add_account(session)
    src = fixture_source()

    assert run(factory, src, lock) is None
    assert src.calls == []
    assert not lock.locked()


def test_pending_request_becomes_done_with_the_mt5_margin(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    src = fixture_source()
    before = db_now(db_engine)

    assert run(factory, src, lock) == request_id

    after = db_now(db_engine)
    row = load(session, request_id)
    assert row.status == "done"
    assert row.margin == D("550")  # 1100.00 per lot * 0.50
    assert row.error_code is None
    assert row.started_at is not None
    assert row.finished_at is not None
    assert before <= row.started_at <= row.finished_at <= after
    assert src.calls == ["connect", "calc_margin", "shutdown"]
    assert src.connect_args == (TERMINAL, LOGIN, SERVER)
    assert src.margin_args == [("buy", "EURUSD", D("0.50"), D("1.10000"))]
    assert not lock.locked()


def test_sell_request_passes_the_direction(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account, direction="sell", volume=D("2"))
    src = fixture_source()

    run(factory, src, lock)

    assert load(session, request_id).margin == D("2199")
    assert src.margin_args == [("sell", "EURUSD", D("2"), D("1.10000"))]


def test_row_is_committed_as_processing_before_mt5_is_called(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    seen: list[tuple[str, bool]] = []

    class Peeking(RecordingSource):
        def calc_margin(self, *args: Any) -> Decimal:
            with factory() as other:  # another connection: sees committed data only
                row = other.get(CalculatorMarginRequest, request_id)
                assert row is not None
                seen.append((row.status, row.started_at is not None))
            return super().calc_margin(*args)

    src = Peeking({"format": 1, "account": ACCOUNT_JSON, "margins": MARGINS})
    run(factory, src, lock)

    assert seen == [("processing", True)]
    assert load(session, request_id).status == "done"


# --- queue order and at most one per run ---


def test_oldest_pending_first_and_at_most_one_per_run(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    newer = add_request(session, account, age_s=5, entry=D("1.20000"))
    older = add_request(session, account, age_s=10, entry=D("1.10000"))
    src = fixture_source()

    assert run(factory, src, lock) == older
    assert load(session, older).status == "done"
    assert load(session, newer).status == "pending"
    assert src.calls.count("calc_margin") == 1

    assert run(factory, src, lock) == newer
    assert load(session, newer).status == "done"
    assert run(factory, src, lock) is None


def test_same_created_at_is_ordered_by_id(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, lock: threading.Lock
) -> None:
    account = add_account(session)
    first = add_request(session, account)
    second = add_request(session, account, entry=D("1.20000"))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE calculator_margin_requests SET created_at = now() - interval '5 seconds',"
                " expires_at = now() + interval '55 seconds'"
            )
        )

    assert run(factory, fixture_source(), lock) == first
    assert load(session, second).status == "pending"


def test_row_locked_by_another_worker_is_skipped(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    locked = add_request(session, account, age_s=10)
    free = add_request(session, account, age_s=5, entry=D("1.20000"))

    with factory() as other:
        other.execute(
            select(CalculatorMarginRequest)
            .where(CalculatorMarginRequest.id == locked)
            .with_for_update()
        ).all()
        assert run(factory, fixture_source(), lock) == free
        other.rollback()

    assert load(session, locked).status == "pending"
    assert load(session, free).status == "done"


@pytest.mark.parametrize("status", ["processing", "done", "failed", "expired"])
def test_only_pending_rows_are_picked(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, status: str
) -> None:
    account = add_account(session)
    request_id = add_request(session, account, age_s=5)
    sql_set = {
        "processing": "status = 'processing', started_at = created_at",
        "done": "status = 'done', started_at = created_at, finished_at = created_at, margin = 1",
        "failed": "status = 'failed', finished_at = created_at, error_code = 'timeout'",
        "expired": "status = 'expired', finished_at = created_at, error_code = 'request_expired'",
    }[status]
    with db_engine.begin() as conn:
        conn.execute(
            text(f"UPDATE calculator_margin_requests SET {sql_set} WHERE id = :id"),  # noqa: S608
            {"id": request_id},
        )
    src = fixture_source()

    assert run(factory, src, threading.Lock()) is None
    assert load(session, request_id).status == status
    assert src.calls == []


# --- expiry ---


def test_request_not_started_within_its_ttl_is_expired_without_mt5(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account, age_s=61)
    src = fixture_source()
    before = db_now(db_engine)

    assert run(factory, src, lock) is None

    row = load(session, request_id)
    assert row.status == "expired"
    assert row.error_code == REQUEST_EXPIRED == "request_expired"
    assert row.started_at is None
    assert row.margin is None
    assert row.finished_at is not None
    assert before <= row.finished_at <= db_now(db_engine)
    assert src.calls == []


def test_overdue_rows_are_expired_and_the_next_live_one_is_handled(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    overdue = [
        add_request(session, account, age_s=age, entry=D(e))
        for age, e in ((90, "1.1"), (70, "1.2"))
    ]
    live = add_request(session, account, age_s=30, entry=D("1.3"))
    src = fixture_source()

    assert run(factory, src, lock) == live

    assert [load(session, i).status for i in overdue] == ["expired", "expired"]
    assert load(session, live).status == "done"
    assert src.calls.count("calc_margin") == 1


def test_processing_row_is_never_expired_by_the_cycle(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, lock: threading.Lock
) -> None:
    """Only requests that were never started expire; a started one finishes or fails."""
    account = add_account(session)
    request_id = add_request(session, account, age_s=120)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE calculator_margin_requests SET status = 'processing', "
                "started_at = created_at + interval '1 second' WHERE id = :id"
            ),
            {"id": request_id},
        )

    run(factory, fixture_source(), lock)

    assert load(session, request_id).status == "processing"


# --- failures ---


@pytest.mark.parametrize(
    "code",
    [Mt5ErrorCode.TIMEOUT, Mt5ErrorCode.TERMINAL_START_FAILED, Mt5ErrorCode.MT5_ERROR],
)
def test_mt5_error_marks_the_request_failed_with_its_code(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock, code: Mt5ErrorCode
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    src = fixture_source()
    src.fail("calc_margin", Mt5Error(code, "scripted"))

    assert run(factory, src, lock) == request_id

    row = load(session, request_id)
    assert row.status == "failed"
    assert row.error_code == code.value
    assert row.margin is None
    assert row.started_at is not None
    assert row.finished_at is not None
    assert row.finished_at >= row.started_at
    assert src.calls[-1] == "shutdown"  # the terminal is always released
    assert not lock.locked()


def test_connect_failure_marks_failed(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    src = fixture_source(failures={"connect": {"last_error": [-6, "Authorization failed"]}})

    run(factory, src, lock)

    row = load(session, request_id)
    assert (row.status, row.error_code) == ("failed", "login_failed")
    assert "calc_margin" not in src.calls


def test_terminal_logged_into_another_account_is_login_failed(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session, login=11111111)
    request_id = add_request(session, account)
    src = fixture_source()

    run(factory, src, lock)

    assert load(session, request_id).error_code == "login_failed"
    assert "calc_margin" not in src.calls


def test_missing_password_is_password_missing(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    src = fixture_source()

    run(factory, src, lock, password_for=lambda _: None)

    row = load(session, request_id)
    assert (row.status, row.error_code) == ("failed", "password_missing")
    assert "calc_margin" not in src.calls


def test_symbol_without_margin_is_mt5_error(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account, symbol="XAUUSD")

    run(factory, fixture_source(), lock)

    assert load(session, request_id).error_code == "mt5_error"


def test_unexpected_error_is_internal_error_and_never_escapes(
    factory: sessionmaker[Session],
    session: Session,
    lock: threading.Lock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)

    class Exploding(RecordingSource):
        def calc_margin(self, *args: Any) -> Decimal:
            raise RuntimeError("driver exploded")

    src = Exploding({"format": 1, "account": ACCOUNT_JSON, "margins": MARGINS})

    assert run(factory, src, lock) == request_id

    row = load(session, request_id)
    assert (row.status, row.error_code) == ("failed", "internal_error")
    assert row.finished_at is not None
    assert "driver exploded" in caplog.text
    assert src.calls[-1] == "shutdown"
    assert not lock.locked()


def test_failure_is_logged_without_the_password(
    factory: sessionmaker[Session],
    session: Session,
    lock: threading.Lock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    src = fixture_source()
    src.fail("calc_margin", Mt5Error(Mt5ErrorCode.TIMEOUT, "IPC timeout"))

    run(factory, src, lock)

    assert str(request_id) in caplog.text
    assert "timeout" in caplog.text
    assert "not-a-real-secret" not in caplog.text


def make_processing(db_engine: Engine, request_id: int, started_s_ago: float) -> None:
    """processing, started ``started_s_ago`` seconds ago (DB clock), created 1 s before."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE calculator_margin_requests SET status = 'processing', "
                "started_at = now() - make_interval(secs => :ago), "
                "created_at = now() - make_interval(secs => :ago + 1), "
                "expires_at = now() - make_interval(secs => :ago + 1) + interval '60 seconds' "
                "WHERE id = :id"
            ),
            {"id": request_id, "ago": started_s_ago},
        )


def test_missing_terminal_path_is_terminal_not_found_without_connecting(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    """Mirrors sync: the real source refuses an empty path the same way (resolve_terminal)."""
    account = add_account(session, terminal_path=None)
    request_id = add_request(session, account)
    src = fixture_source()

    assert run(factory, src, lock) == request_id

    row = load(session, request_id)
    assert (row.status, row.error_code) == ("failed", "terminal_not_found")
    assert "connect" not in src.calls


# --- stuck processing rows (lost result, worker died) ---


def test_stale_processing_row_is_swept_to_interrupted(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, lock: threading.Lock
) -> None:
    account = add_account(session)
    stale = add_request(session, account)
    fresh = add_request(session, account, entry=D("1.2"))
    make_processing(db_engine, stale, STALE_PROCESSING_S + 5)
    make_processing(db_engine, fresh, STALE_PROCESSING_S - 30)
    src = fixture_source()

    assert run(factory, src, lock) is None

    row = load(session, stale)
    assert (row.status, row.error_code) == ("failed", INTERRUPTED)
    assert row.finished_at is not None
    assert row.margin is None
    assert load(session, fresh).status == "processing"
    assert src.calls == []


def test_stale_sweep_never_runs_while_the_lock_is_held(
    factory: sessionmaker[Session], session: Session, db_engine: Engine, lock: threading.Lock
) -> None:
    account = add_account(session)
    stale = add_request(session, account)
    make_processing(db_engine, stale, STALE_PROCESSING_S + 5)

    with lock:
        assert run(factory, fixture_source(), lock) is None

    assert load(session, stale).status == "processing"


def test_finish_failure_is_logged_and_the_row_is_swept_later(
    factory: sessionmaker[Session],
    session: Session,
    db_engine: Engine,
    lock: threading.Lock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)

    def broken_finish(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("db went away while storing")

    with monkeypatch.context() as patch:
        patch.setattr(margin_job, "finish", broken_finish)
        run(factory, fixture_source(), lock)

    assert not lock.locked()
    assert load(session, request_id).status == "processing"  # the result is lost
    logged = [r for r in caplog.records if r.exc_info and str(request_id) in r.getMessage()]
    assert logged, caplog.text
    assert "db went away while storing" in caplog.text

    make_processing(db_engine, request_id, STALE_PROCESSING_S + 5)  # time passes
    run(factory, fixture_source(), lock)

    row = load(session, request_id)
    assert (row.status, row.error_code) == ("failed", INTERRUPTED)


@pytest.mark.parametrize(
    ("margin", "code", "kind"),
    [(D("550"), None, "done"), (None, "timeout", "failed")],
)
def test_finish_on_a_row_no_longer_processing_warns_and_changes_nothing(
    session: Session,
    db_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    margin: Decimal | None,
    code: str | None,
    kind: str,
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    make_processing(db_engine, request_id, 1)
    with db_engine.begin() as conn:  # e.g. swept as interrupted meanwhile
        conn.execute(
            text(
                "UPDATE calculator_margin_requests SET status = 'failed', "
                "finished_at = now(), error_code = 'interrupted' WHERE id = :id"
            ),
            {"id": request_id},
        )

    finish(session, request_id, margin, code)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(str(request_id) in r.getMessage() and kind in r.getMessage() for r in warnings)
    row = load(session, request_id)
    assert (row.status, row.error_code, row.margin) == ("failed", "interrupted", None)


# --- lock shared with sync ---


def test_does_nothing_while_the_lock_is_held(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    request_id = add_request(session, account)
    src = fixture_source()

    with lock:  # sync is running
        assert run(factory, src, lock) is None
        assert lock.locked()  # never released by the margin job

    assert load(session, request_id).status == "pending"
    assert src.calls == []


def test_lock_is_held_while_mt5_is_used(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    account = add_account(session)
    add_request(session, account)
    src = fixture_source(lock)

    run(factory, src, lock)

    assert src.lock_held_at_connect == [True]
    assert not lock.locked()


def test_does_not_wait_for_the_lock(
    factory: sessionmaker[Session], session: Session, lock: threading.Lock
) -> None:
    """Non-blocking acquire: a held lock returns at once, not after the holder finishes."""
    account = add_account(session)
    add_request(session, account)
    release = threading.Event()
    holding = threading.Event()

    def hold() -> None:
        with lock:
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert holding.wait(5)
        assert run(factory, fixture_source(), lock) is None
    finally:
        release.set()
        holder.join(5)


@pytest.fixture
def rules() -> RulesConfig:
    return get_rules()


@pytest.fixture
def env_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config as app_config

    monkeypatch.setenv(app_config.mt5_password_key(LOGIN), "not-a-real-secret")


@pytest.mark.usefixtures("env_password")
def test_sync_cycle_holds_the_shared_lock_for_the_whole_cycle(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig, lock: threading.Lock
) -> None:
    add_account(session)
    src = fixture_source(lock)

    run_sync_cycle(factory, src, lock=lock, rules_getter=lambda: rules)

    assert src.lock_held_at_connect == [True]  # the fresh account is due
    assert not lock.locked()


@pytest.mark.usefixtures("env_password")
def test_sync_cycle_waits_for_a_running_margin_request(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig, lock: threading.Lock
) -> None:
    """Sync keeps priority but never enters MT5 while the margin job is inside it:
    it waits (blocking acquire) instead of skipping the cycle."""
    add_account(session)
    released = threading.Event()
    connect_after_release: list[bool] = []

    class Watching(RecordingSource):
        def connect(self, *args: Any, **kwargs: Any) -> RawAccountInfo:
            connect_after_release.append(released.is_set())
            return super().connect(*args, **kwargs)

    src = Watching({"format": 1, "account": ACCOUNT_JSON, "margins": MARGINS}, lock)
    lock.acquire()

    def release_later() -> None:
        threading.Event().wait(0.2)
        released.set()
        lock.release()

    holder = threading.Thread(target=release_later)
    holder.start()
    try:
        run_sync_cycle(factory, src, lock=lock, rules_getter=lambda: rules)
    finally:
        holder.join(5)

    assert connect_after_release == [True]
    assert not lock.locked()


# --- worker start: interrupted requests ---


def test_interrupted_processing_rows_become_failed_at_start(
    factory: sessionmaker[Session], session: Session, db_engine: Engine
) -> None:
    account = add_account(session)
    processing = add_request(session, account, age_s=30)
    pending = add_request(session, account, age_s=5, entry=D("1.2"))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE calculator_margin_requests SET status = 'processing', "
                "started_at = created_at + interval '1 second' WHERE id = :id"
            ),
            {"id": processing},
        )
    before = db_now(db_engine)

    assert mark_interrupted_margin_requests(factory) == 1

    row = load(session, processing)
    assert row.status == "failed"
    assert row.error_code == INTERRUPTED == "interrupted"
    assert row.started_at is not None
    assert row.finished_at is not None
    assert before <= row.finished_at <= db_now(db_engine)
    assert row.margin is None
    assert load(session, pending).status == "pending"


def test_interrupted_cleanup_without_rows_returns_zero(factory: sessionmaker[Session]) -> None:
    assert mark_interrupted_margin_requests(factory) == 0


def test_interrupted_cleanup_logs_and_swallows_db_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> Session:
        raise RuntimeError("db down")

    assert mark_interrupted_margin_requests(broken) == 0  # type: ignore[arg-type]
    assert "interrupted margin" in caplog.text.lower()

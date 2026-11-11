"""MT5 sync service against the fixture source and the test DB.

Expected values come from tests/fixtures/mt5/README.md (ground truth). Rules come from the
real config/rules.yaml.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.api import sync_status as sync_status_api
from app.config import Settings
from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.config_files.symbols import SymbolsConfig
from app.db import make_session_factory
from app.domain.trade_builder import SkippedPosition
from app.models import Account, RuleViolation, SymbolSpec, SyncLog, Trade, TradeExitDeal
from app.models.enums import AccountPhase, AccountStatus
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from app.mt5.real import RealMt5Source
from app.mt5.source import Mt5Source
from app.mt5.types import (
    Direction,
    RawAccountInfo,
    RawDeal,
    RawOrder,
    RawPosition,
    RawQuote,
    RawSymbolSpec,
)
from app.services import sync as sync_service
from app.services.sync import close_orphaned_runs, is_due, sync_account
from app.worker import sync_job
from app.worker.sync_job import make_source, run_sync_cycle

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mt5"
SERVER = "FundedNext-Server"
WEEK_LOGIN = 51234567
DST_LOGIN = 51234568
FAIL_LOGIN = 51234569
# basic_week step 0: Fri 2026-10-23 10:00 UTC (12:00 Brussels, trading hours).
WEEK_NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
WEEK_STEP1_NOW = datetime(2026, 10, 23, 13, 31, tzinfo=UTC)
DST_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
FAIL_NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
# The real symbols.yaml names, without its FundedNext override (GER40 -> only GER30): these
# fixtures predate M5-08 and name the DAX GER40, so the watch list and tick detection keep
# finding it. The FundedNext GER30 case is tests/test_canonical_symbols.py.
SYMBOLS = SymbolsConfig.model_validate(
    {
        "symbols": [
            {"name": "EURUSD"},
            {"name": "GBPUSD"},
            {"name": "XAUUSD"},
            {"name": "GER40", "broker_names": ["GER30", "GER40.cash", "DE40"]},
        ]
    }
)


def password(_: int) -> SecretStr:
    return SecretStr("not-a-real-secret")


def utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


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
def rules() -> RulesConfig:
    return get_rules()


def add_account(session: Session, login: int, name: str | None = None, **kw: Any) -> Account:
    defaults: dict[str, Any] = {
        "name": name or f"FN {login}",
        "firm": "FundedNext",
        "program": "Stellar 2-Step",
        "phase": AccountPhase.PHASE_1.value,
        "login": login,
        "server": SERVER,
        "terminal_path": "D:\\MT5\\fn\\terminal64.exe",
        "starting_balance": Decimal("100000.00"),
        "currency": "USD",
    }
    account = Account(**(defaults | kw))  # overrides (e.g. firm) win
    session.add(account)
    session.commit()
    return account


def source(name: str, step: int = 0) -> FixtureMt5Source:
    return FixtureMt5Source.from_file(FIXTURES / name, step=step)


def run(
    session: Session, account: Account, src: Mt5Source, rules: RulesConfig, now: datetime
) -> SyncLog:
    return sync_account(session, account, src, rules, now, password_for=password, symbols=SYMBOLS)


def trades_by_pid(session: Session, account_id: int) -> dict[int, Trade]:
    session.expire_all()
    return {
        t.position_id: t
        for t in session.scalars(select(Trade).where(Trade.account_id == account_id))
    }


def violations(session: Session, trade: Trade) -> list[str]:
    return sorted(
        session.scalars(select(RuleViolation.rule_key).where(RuleViolation.trade_id == trade.id))
    )


def D(value: str) -> Decimal:  # noqa: N802 - short Decimal constructor for tables
    return Decimal(value)


# --- basic_week ------------------------------------------------------------------------

# pid: session, entry, exit, net, initial_sl, source, risk, risk_pct, R, planned RR, status
EXPECTED: dict[int, tuple[Any, ...]] = {
    2000101: ("london", "1.165", "1.1679", "284.00", "1.162", "deal", "300.00", "0.3000",
              "0.9467", "1.6667", "needs_description"),
    2000201: ("ny", "1.3405", "1.337", "344.00", "1.344", "order", "350.00", None,
              "0.9829", "1.0000", "needs_description"),
    2000301: ("london", "4105.5", "4095.5", "-503.00", "4095.5", "deal", "500.00", "0.4969",
              "-1.0060", "2.0000", "needs_description"),
    2000401: ("london", "4093", "4103", "497.00", "4086", "deal", "350.00", None,
              "1.4200", "2.4286", "needs_description"),
    2000501: ("premarket", "24150", "24110", "92.80", None, None, None, None,
              None, None, "needs_sl"),
    2000601: ("ny", "24200", "24260", "348.00", "24170", "order", "174.00", "0.1728",
              "2.0000", "3.0000", "needs_description"),
    2000701: ("london", "1.163", None, "-2.40", "1.165", "position", "160.00", None,
              None, "2.0000", "open"),
}  # fmt: skip


def _opt(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def test_basic_week_full_sync(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    log = run(session, account, source("basic_week.json"), rules, WEEK_NOW)

    assert log.ok is True, log.error_message
    assert log.error_code is None
    assert log.trades_created == 7
    assert log.trades_updated == 0
    assert log.open_positions == 1
    assert log.symbols_synced == 4
    assert log.server_offset_hours == 3
    assert log.finished_at is not None
    assert log.finished_at >= log.started_at

    trades = trades_by_pid(session, account.id)
    assert set(trades) == set(EXPECTED)
    for pid, exp in EXPECTED.items():
        t = trades[pid]
        session_name, entry, exit_, net, sl, src, risk, risk_pct, r, rr, status = exp
        assert t.session == session_name, pid
        assert t.entry_price == D(entry), pid
        assert t.exit_price == _opt(exit_), pid
        assert t.net_pnl == D(net), pid
        assert t.initial_sl == _opt(sl), pid
        assert t.initial_sl_source == src, pid
        assert t.risk_amount == _opt(risk), pid
        if risk_pct is not None:
            assert t.risk_pct == D(risk_pct), pid
        assert t.r_multiple == _opt(r), pid
        assert t.planned_rr == _opt(rr), pid
        assert t.status == status, pid

    t1, t3, t6, t7 = (trades[p] for p in (2000101, 2000301, 2000601, 2000701))
    assert (t1.open_time, t1.close_time) == (utc(10, 19, 7, 30), utc(10, 19, 9, 30))
    assert t1.duration_seconds == 7200
    assert (t1.weekday, t1.hour) == (0, 9)  # Monday 09:30 Brussels
    assert t1.balance_at_open == D("100000.00")
    assert t3.balance_at_open == D("100628.00")
    assert t6.balance_at_open == D("100714.80")
    assert t1.pnl_pct == D("0.2840")
    assert t7.close_time is None
    assert t7.pnl_pct is None
    assert t7.last_sl == D("1.165")
    assert trades[2000401].is_reentry is True
    assert [p for p, t in trades.items() if t.is_reentry] == [2000401]

    exits = session.scalars(
        select(TradeExitDeal).where(TradeExitDeal.trade_id == t1.id).order_by(TradeExitDeal.time)
    ).all()
    assert [e.volume for e in exits] == [D("0.4"), D("0.3"), D("0.3")]
    assert trades[2000201].id is not None

    assert {p: violations(session, t) for p, t in trades.items() if violations(session, t)} == {
        2000201: ["min_planned_rr"],
        2000501: ["entry_session"],
    }

    session.refresh(account)
    assert account.balance == D("101060.40")
    assert account.equity == D("101100.40")
    assert account.balance_synced_at == WEEK_NOW
    assert account.server_offset_hours == 3
    assert account.server_offset_detected_at == WEEK_NOW
    specs = {s.symbol: s for s in session.scalars(select(SymbolSpec))}
    assert set(specs) == {"EURUSD", "GBPUSD", "XAUUSD", "GER40"}
    assert specs["GER40"].tick_value == D("0.0116")


def test_second_sync_is_idempotent(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = source("basic_week.json")
    run(session, account, src, rules, WEEK_NOW)
    before = {
        "trades": session.scalar(select(func.count()).select_from(Trade)),
        "exits": session.scalar(select(func.count()).select_from(TradeExitDeal)),
        "violations": session.scalar(select(func.count()).select_from(RuleViolation)),
        "specs": session.scalar(select(func.count()).select_from(SymbolSpec)),
    }
    log = run(session, account, src, rules, WEEK_NOW + timedelta(minutes=1))
    assert log.ok is True
    assert (log.trades_created, log.trades_updated) == (0, 0)
    after = {
        "trades": session.scalar(select(func.count()).select_from(Trade)),
        "exits": session.scalar(select(func.count()).select_from(TradeExitDeal)),
        "violations": session.scalar(select(func.count()).select_from(RuleViolation)),
        "specs": session.scalar(select(func.count()).select_from(SymbolSpec)),
    }
    assert after == before == {"trades": 7, "exits": 8, "violations": 2, "specs": 4}


def test_step_advance_closes_open_trade_and_keeps_journal(
    session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = source("basic_week.json")
    run(session, account, src, rules, WEEK_NOW)

    trades = trades_by_pid(session, account.id)
    t1 = trades[2000101]
    t1.status = "draft"
    t1.setup_context = "yes"
    t1.lesson = "patience"
    session.add(RuleViolation(trade_id=t1.id, rule_key="no_breakeven", source="user"))
    t7 = trades[2000701]
    # first-seen SL was persisted while the position was open
    assert (t7.initial_sl, t7.initial_sl_source, t7.status) == (D("1.165"), "position", "open")
    session.commit()

    src.advance()
    log = run(session, account, src, rules, WEEK_STEP1_NOW)
    assert log.ok is True, log.error_message
    assert log.trades_created == 0
    assert log.trades_updated == 1  # only T7
    assert log.open_positions == 0

    trades = trades_by_pid(session, account.id)
    t7 = trades[2000701]
    assert t7.status == "needs_description"
    assert t7.close_time == utc(10, 23, 13, 30)
    assert t7.net_pnl == D("235.20")
    assert (t7.initial_sl, t7.initial_sl_source) == (D("1.165"), "position")
    assert t7.risk_amount == D("160.00")
    assert t7.r_multiple == D("1.4700")
    t1 = trades[2000101]
    assert (t1.status, t1.setup_context, t1.lesson) == ("draft", "yes", "patience")
    assert violations(session, t1) == ["no_breakeven"]
    session.refresh(account)
    assert account.balance == D("101298.00")


def test_never_seen_open_position_needs_sl(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    log = run(session, account, source("basic_week.json", step=1), rules, WEEK_STEP1_NOW)
    assert log.ok is True
    t7 = trades_by_pid(session, account.id)[2000701]
    assert (t7.status, t7.initial_sl, t7.risk_amount) == ("needs_sl", None, None)


def test_user_sl_survives_sync(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = source("basic_week.json")
    run(session, account, src, rules, WEEK_NOW)
    t5 = trades_by_pid(session, account.id)[2000501]
    t5.initial_sl = D("24170")
    t5.initial_sl_source = "user"
    t5.status = "needs_description"
    session.commit()

    log = run(session, account, src, rules, WEEK_NOW + timedelta(minutes=1))
    assert log.ok is True
    t5 = trades_by_pid(session, account.id)[2000501]
    assert (t5.initial_sl, t5.initial_sl_source, t5.status) == (
        D("24170"),
        "user",
        "needs_description",
    )
    assert t5.risk_amount == D("46.40")  # 92.80 * 20 / 40
    assert t5.planned_rr is None  # no TP
    assert violations(session, t5) == ["entry_session"]


# --- dst_switch ------------------------------------------------------------------------


def test_dst_switch(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, DST_LOGIN)
    log = run(session, account, source("dst_switch.json"), rules, DST_NOW)
    assert log.ok is True, log.error_message
    assert log.server_offset_hours == 2
    trades = trades_by_pid(session, account.id)
    d1, d2, d3, d4 = (trades[p] for p in (4000101, 4000201, 4000301, 4000401))
    assert (d1.open_time, d1.session) == (utc(10, 23, 7, 30), "london")
    assert (d2.open_time, d2.session) == (utc(10, 26, 11, 30), "premarket")
    assert (d3.open_time, d3.close_time) == (utc(10, 30, 19), utc(11, 2, 8, 30))
    assert d3.duration_seconds == 221_400
    assert (d3.session, d3.net_pnl, d3.swap) == ("outside", D("178.60"), D("-15.40"))
    assert (d4.open_time, d4.session) == (utc(11, 2, 8, 45), "london")
    assert d4.balance_at_open == D("49197.60")
    assert violations(session, d2) == ["entry_session"]
    # D3: sell 1.165, SL 1.168, TP 1.161 -> planned RR 1.3333 < 1.5
    assert d3.planned_rr == D("1.3333")
    assert violations(session, d3) == ["entry_session", "min_planned_rr"]
    session.refresh(account)
    assert account.balance == D("49244.60")
    assert account.server_offset_hours == 2


# --- failures --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("fail_login.json", "login_failed"),
        ("fail_terminal_not_found.json", "terminal_not_found"),
        ("fail_timeout_mid_sync.json", "timeout"),
        ("fail_then_recover.json", "terminal_start_failed"),
    ],
)
def test_failures_are_recorded(
    session: Session, rules: RulesConfig, fixture: str, code: str
) -> None:
    account = add_account(session, FAIL_LOGIN)
    src = source(fixture)
    log = run(session, account, src, rules, FAIL_NOW)
    assert log.ok is False
    assert log.error_code == code
    assert log.error_message
    assert log.finished_at is not None
    assert src.calls[-1] == "shutdown" or "connect" in src.calls
    assert trades_by_pid(session, account.id) == {}
    session.refresh(account)
    assert account.balance is None


def test_fail_then_recover_and_failure_keeps_previous_data(
    session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, FAIL_LOGIN)
    src = source("fail_then_recover.json")
    assert run(session, account, src, rules, FAIL_NOW).error_code == "terminal_start_failed"
    src.advance()
    log = run(session, account, src, rules, FAIL_NOW + timedelta(minutes=1))
    assert log.ok is True, log.error_message
    (trade,) = trades_by_pid(session, account.id).values()
    assert trade.net_pnl == D("19.40")
    assert trade.status == "needs_description"

    src.fail("deals", Mt5Error(Mt5ErrorCode.TIMEOUT, "deals failed: IPC timeout"))
    log = run(session, account, src, rules, FAIL_NOW + timedelta(minutes=2))
    assert (log.ok, log.error_code) == (False, "timeout")
    assert [t.net_pnl for t in trades_by_pid(session, account.id).values()] == [D("19.40")]
    rows = session.scalars(select(SyncLog.ok).order_by(SyncLog.id)).all()
    assert rows == [False, True, False]


def test_password_missing(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = source("basic_week.json")
    log = sync_account(session, account, src, rules, WEEK_NOW, password_for=lambda _: None)
    assert (log.ok, log.error_code) == (False, "password_missing")
    assert log.error_message == f"MT5_PASSWORD_{WEEK_LOGIN} is not set in .env"
    assert src.calls == []  # the terminal is not even started


def test_unexpected_error_rolls_back(
    session: Session, rules: RulesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = add_account(session, WEEK_LOGIN)
    real_write = sync_service.write

    def exploding(*args: Any, **kwargs: Any) -> Any:
        real_write(*args, **kwargs)  # rows written, then the cycle fails
        raise RuntimeError("boom")

    monkeypatch.setattr(sync_service, "write", exploding)
    log = run(session, account, source("basic_week.json"), rules, WEEK_NOW)
    assert (log.ok, log.error_code) == (False, "internal_error")
    assert log.error_message == "RuntimeError: boom"
    assert trades_by_pid(session, account.id) == {}
    session.refresh(account)
    assert account.balance is None


def test_password_never_logged(
    session: Session, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    account = add_account(session, 1)  # wrong login -> login_failed message
    run(session, account, source("basic_week.json"), rules, WEEK_NOW)
    assert "not-a-real-secret" not in caplog.text


# --- history window, cadence -----------------------------------------------------------


def test_history_window(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    sync = rules.sync
    first = sync_service.history_window_start(session, account.id, sync, WEEK_NOW)
    assert first == WEEK_NOW - timedelta(days=sync.initial_history_days)
    run(session, account, source("basic_week.json"), rules, WEEK_NOW)
    later = sync_service.history_window_start(
        session, account.id, sync, WEEK_NOW + timedelta(hours=1)
    )
    assert later == WEEK_NOW - timedelta(days=sync.overlap_days)


def test_is_due_follows_cadence(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    assert is_due(session, account.id, rules, WEEK_NOW)
    session.add(SyncLog(account_id=account.id, started_at=WEEK_NOW, ok=True))
    session.commit()
    # Friday 12:00 Brussels: trading hours, 60 s
    assert not is_due(session, account.id, rules, WEEK_NOW + timedelta(seconds=20))
    assert is_due(session, account.id, rules, WEEK_NOW + timedelta(seconds=58))
    # Saturday: idle, 900 s
    saturday = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
    session.add(SyncLog(account_id=account.id, started_at=saturday, ok=True))
    session.commit()
    assert not is_due(session, account.id, rules, saturday + timedelta(minutes=5))
    assert is_due(session, account.id, rules, saturday + timedelta(minutes=15))


def test_close_orphaned_runs(session: Session) -> None:
    account = add_account(session, WEEK_LOGIN)
    session.add(SyncLog(account_id=account.id, started_at=WEEK_NOW, ok=None))
    session.add(SyncLog(account_id=account.id, started_at=WEEK_NOW, ok=True))
    session.commit()
    assert close_orphaned_runs(session, WEEK_NOW) == 1
    row = session.scalars(select(SyncLog).where(SyncLog.ok.is_(False))).one()
    assert row.error_code == "internal_error"


# --- worker cycle ----------------------------------------------------------------------


@pytest.fixture
def env_passwords(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    for login in (WEEK_LOGIN, 111):
        monkeypatch.setenv(config.mt5_password_key(login), "not-a-real-secret")


@pytest.mark.usefixtures("env_passwords")
def test_cycle_isolates_accounts(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig
) -> None:
    wrong = add_account(session, 111, "A wrong login")
    good = add_account(session, WEEK_LOGIN, "B good")
    add_account(session, 222, "C archived", status=AccountStatus.ARCHIVED.value)
    add_account(session, 333, "D passed", status=AccountStatus.PASSED.value)
    src = source("basic_week.json")

    synced = run_sync_cycle(factory, src, now=lambda: WEEK_NOW, rules_getter=lambda: rules)
    assert synced == [wrong.id, good.id]
    logs = {row.account_id: row for row in session.scalars(select(SyncLog))}
    assert set(logs) == {wrong.id, good.id}
    assert (logs[wrong.id].ok, logs[wrong.id].error_code) == (False, "login_failed")
    assert logs[good.id].ok is True
    assert len(trades_by_pid(session, good.id)) == 7

    # Not due 20 s later: nothing runs.
    later = WEEK_NOW + timedelta(seconds=20)
    assert run_sync_cycle(factory, src, now=lambda: later, rules_getter=lambda: rules) == []


@pytest.mark.usefixtures("env_passwords")
def test_cycle_survives_unexpected_exception(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = add_account(session, 111, "A")
    second = add_account(session, WEEK_LOGIN, "B")
    real = sync_account

    def flaky(db: Session, account: Account, *args: Any, **kwargs: Any) -> SyncLog:
        if account.id == first.id:
            raise RuntimeError("database went away")
        return real(db, account, *args, **kwargs)

    monkeypatch.setattr(sync_job, "sync_account", flaky)
    synced = run_sync_cycle(
        factory, source("basic_week.json"), now=lambda: WEEK_NOW, rules_getter=lambda: rules
    )
    assert synced == [second.id]
    assert f"MT5 sync of account {first.id} failed" in caplog.text


def test_cycle_skips_when_rules_broken(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    from app.config_files import ConfigError

    def broken() -> RulesConfig:
        raise ConfigError(Path("rules.yaml"), ["sync: missing"])

    assert run_sync_cycle(factory, source("basic_week.json"), rules_getter=broken) == []
    assert "MT5 sync skipped" in caplog.text


def test_make_source(settings: Settings) -> None:
    assert isinstance(
        make_source(settings.model_copy(update={"mt5_source": "real"})), RealMt5Source
    )
    fixture = make_source(
        settings.model_copy(
            update={"mt5_source": "fixture:backend/tests/fixtures/mt5/basic_week.json"}
        )
    )
    assert isinstance(fixture, FixtureMt5Source)
    with pytest.raises(ValueError, match="MT5_SOURCE"):
        make_source(settings.model_copy(update={"mt5_source": "demo"}))


# --- PATCH initial_sl uses the same recompute --------------------------------------------


def test_patch_initial_sl_recomputes_violations(
    client: TestClient, session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, WEEK_LOGIN)
    run(session, account, source("basic_week.json"), rules, WEEK_NOW)
    t5 = trades_by_pid(session, account.id)[2000501]

    response = client.patch(f"/api/trades/{t5.id}", json={"initial_sl": "24700.00"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "needs_description"
    assert data["initial_sl_source"] == "user"
    assert data["risk_amount"] == "1276.00"  # 92.80 / (40 * 2) * 550 * 2
    assert data["violations"] == ["entry_session", "max_risk_pct"]

    data = client.patch(f"/api/trades/{t5.id}", json={"initial_sl": "24170.00"}).json()
    assert data["risk_amount"] == "46.40"
    assert data["violations"] == ["entry_session"]


# --- review fixes: old open position, stale ticks, cadence drift, skipped positions ------


class Wrapped:
    """Fixture source plus extra deals/positions and scripted ticks (an `Mt5Source`)."""

    def __init__(
        self,
        base: FixtureMt5Source,
        *,
        deals: Sequence[RawDeal] = (),
        positions: Sequence[RawPosition] = (),
        ticks: dict[str, int] | None = None,
    ) -> None:
        self.base = base
        self.extra_deals = list(deals)
        self.extra_positions = list(positions)
        self.ticks = ticks

    def connect(
        self,
        terminal_path: str,
        login: int,
        password: SecretStr | None,
        server: str,
        timeout_s: float = 60.0,
    ) -> RawAccountInfo:
        return self.base.connect(terminal_path, login, password, server, timeout_s)

    def shutdown(self) -> None:
        self.base.shutdown()

    def account_info(self) -> RawAccountInfo:
        return self.base.account_info()

    def server_tick_epoch(self, symbol: str) -> int | None:
        real = self.base.server_tick_epoch(symbol)  # keeps the connection check
        return real if self.ticks is None else self.ticks.get(symbol)

    def symbol_spec(self, symbol: str) -> RawSymbolSpec | None:
        return self.base.symbol_spec(symbol)

    def symbols_matching(self, prefixes: Iterable[str]) -> list[RawSymbolSpec]:
        return self.base.symbols_matching(prefixes)

    def deals(self, from_server_epoch: int, to_server_epoch: int) -> list[RawDeal]:
        extra = [d for d in self.extra_deals if from_server_epoch <= d.time <= to_server_epoch]
        found = self.base.deals(from_server_epoch, to_server_epoch) + extra
        return sorted(found, key=lambda d: (d.time, d.ticket))

    def deals_for_position(self, position_id: int) -> list[RawDeal]:
        own = [d for d in self.extra_deals if d.position_id == position_id]
        return own or self.base.deals_for_position(position_id)

    def opening_order(self, order_ticket: int) -> RawOrder | None:
        return self.base.opening_order(order_ticket)

    def open_positions(self) -> list[RawPosition]:
        return self.base.open_positions() + self.extra_positions

    def calc_margin(
        self, direction: Direction, symbol: str, volume: Decimal, price: Decimal
    ) -> Decimal:
        return self.base.calc_margin(direction, symbol, volume, price)

    def quote(self, symbol: str) -> RawQuote | None:
        return self.base.quote(symbol)

    def calc_profit(
        self,
        direction: Direction,
        symbol: str,
        volume: Decimal,
        price_open: Decimal,
        price_close: Decimal,
    ) -> Decimal:
        return self.base.calc_profit(direction, symbol, volume, price_open, price_close)


def wall_epoch(wall: datetime) -> int:
    """MT5 epoch of a server wall-clock time (given tagged as UTC)."""
    return int(wall.timestamp())


OLD_PID = 2999901
OLD_OPEN = wall_epoch(datetime(2026, 10, 16, 13, 0, tzinfo=UTC))  # Fri 10:00 UTC
OLD_ENTRY = RawDeal(
    ticket=1999901,
    order=OLD_PID,
    position_id=OLD_PID,
    time=OLD_OPEN,
    type=0,
    entry=0,
    volume=D("0.10"),
    price=D("1.16000"),
    profit=D("0"),
    symbol="EURUSD",
    sl=D("1.15000"),
)
OLD_POSITION = RawPosition(
    ticket=OLD_PID,
    identifier=OLD_PID,
    time=OLD_OPEN,
    type=0,
    volume=D("0.10"),
    price_open=D("1.16000"),
    sl=D("1.15000"),
    tp=D("0"),
    price_current=D("1.16100"),
    profit=D("10"),
    symbol="EURUSD",
)


def test_position_older_than_window_does_not_duplicate(
    session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = Wrapped(source("basic_week.json"), deals=[OLD_ENTRY], positions=[OLD_POSITION])
    first = run(session, account, src, rules, WEEK_NOW)
    assert (first.ok, first.trades_created) == (True, 8), first.error_message
    # The window now starts 3 days back; the old open position widens the balance fetch
    # to the whole week, which must not rebuild (and re-insert) the other trades.
    second = run(session, account, src, rules, WEEK_NOW + timedelta(minutes=1))
    assert second.ok is True, second.error_message
    assert (second.trades_created, second.trades_updated) == (0, 0)
    trades = trades_by_pid(session, account.id)
    assert len(trades) == 8
    assert (trades[OLD_PID].status, trades[OLD_PID].initial_sl) == ("open", D("1.15"))
    assert trades[2000301].balance_at_open == D("100628.00")


def test_stale_weekend_tick_uses_rule(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    # Friday close 21:00 UTC = Sat 00:00 server; at Sat 01:00 UTC the stale tick sits
    # exactly on a whole hour and would "detect" UTC-1.
    saturday = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
    stale = wall_epoch(datetime(2026, 10, 24, 0, 0, tzinfo=UTC))
    src = Wrapped(source("basic_week.json"), ticks={"EURUSD": stale, "GER40": stale})
    log = run(session, account, src, rules, saturday)
    assert log.ok is True, log.error_message
    assert log.server_offset_hours == 3  # ny_close rule, not the bogus -1
    session.refresh(account)
    assert account.server_offset_detected_at is None
    t1 = trades_by_pid(session, account.id)[2000101]
    assert (t1.open_time, t1.session) == (utc(10, 19, 7, 30), "london")


def test_newest_tick_wins(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    fresh = wall_epoch(WEEK_NOW + timedelta(hours=3))
    quiet = wall_epoch(WEEK_NOW + timedelta(hours=1))  # 2 h old tick on a quiet symbol
    src = Wrapped(source("basic_week.json"), ticks={"EURUSD": quiet, "GER40": fresh})
    log = run(session, account, src, rules, WEEK_NOW)
    assert log.server_offset_hours == 3
    session.refresh(account)
    assert account.server_offset_detected_at == WEEK_NOW


def test_is_due_tolerates_start_drift(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    last = WEEK_NOW + timedelta(seconds=10)  # the previous cycle reached it late
    session.add(SyncLog(account_id=account.id, started_at=last, ok=True))
    session.commit()
    assert not is_due(session, account.id, rules, last + timedelta(seconds=25))
    assert is_due(session, account.id, rules, WEEK_NOW + timedelta(seconds=61))


@pytest.mark.usefixtures("env_passwords")
def test_variable_timing_still_syncs_every_account_each_cycle(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig
) -> None:
    first = add_account(session, 111, "A")
    second = add_account(session, WEEK_LOGIN, "B")
    src = source("basic_week.json")
    # Cycle 1: B starts 40 s in (slow connect of A); cycle 2: A takes only 15 s, so B is
    # reached 35 s after its previous start. A 5 s slack would skip it (every 120 s).
    clock = iter([WEEK_NOW, WEEK_NOW + timedelta(seconds=40)])
    synced = run_sync_cycle(factory, src, now=lambda: next(clock), rules_getter=lambda: rules)
    assert synced == [first.id, second.id]
    clock = iter([WEEK_NOW + timedelta(seconds=60), WEEK_NOW + timedelta(seconds=75)])
    synced = run_sync_cycle(factory, src, now=lambda: next(clock), rules_getter=lambda: rules)
    assert synced == [first.id, second.id]


ORPHAN_PID = 2888801
ORPHAN_EXIT = RawDeal(
    ticket=1888801,
    order=1888801,
    position_id=ORPHAN_PID,
    time=wall_epoch(datetime(2026, 10, 22, 15, 0, tzinfo=UTC)),
    type=1,
    entry=1,
    volume=D("0.10"),
    price=D("1.16000"),
    profit=D("5"),
    symbol="EURUSD",
)


def test_skipped_positions_recorded_as_warning(
    app: FastAPI, client: TestClient, session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = Wrapped(source("basic_week.json"), deals=[ORPHAN_EXIT])
    log = run(session, account, src, rules, WEEK_NOW)
    assert log.ok is True
    assert log.trades_created == 7
    assert log.error_code == "positions_skipped"
    assert log.error_message is not None
    assert log.error_message.startswith(f"1 positions skipped: {ORPHAN_PID}: exit deal 1888801")

    app.dependency_overrides[sync_status_api.utc_now] = lambda: WEEK_NOW + timedelta(seconds=5)
    try:
        item = client.get("/api/sync/status").json()["items"][0]
    finally:
        app.dependency_overrides.pop(sync_status_api.utc_now, None)
    assert item["state"] == "warning"
    assert item["error_code"] == "positions_skipped"
    assert item["error_message"] == log.error_message


def test_skipped_message_is_capped() -> None:
    skipped = [SkippedPosition(i, "x" * 40) for i in range(50)]
    message = sync_service._short(sync_service.skipped_message(skipped))
    assert message.startswith("50 positions skipped: 0: ")
    assert len(message) == sync_service.MAX_ERROR_MESSAGE

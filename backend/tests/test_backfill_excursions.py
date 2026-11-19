"""M8-16 backfill tool: dry run prints and writes nothing, --apply stores, refuses while
the worker syncs (fixture MT5 source, same data as test_excursions_sync)."""

# ruff: noqa: F811  (pytest fixtures imported from test_excursions_sync)
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config_files.rules import RulesConfig
from app.models import Account
from app.mt5.fixture import FixtureMt5Source
from app.tools.backfill_excursions import BackfillError, Totals, run, summary
from tests.test_excursions_sync import (  # noqa: F401 (fixtures)
    NOW,
    NOW_SERVER,
    SHORT_PID,
    _clean,
    account,
    data,
    rules,
    session,
)
from tests.test_sync import password, trades_by_pid
from tests.test_sync import run as sync_run

LATER = NOW + timedelta(minutes=30)  # the worker is stopped: last sync 30 min ago


@pytest.fixture
def synced(session: Session, account: Account, rules: RulesConfig) -> Account:
    """One sync creates the trades (no MAE/MFE yet: that is the next sync)."""
    assert sync_run(session, account, FixtureMt5Source(data(NOW_SERVER)), rules, NOW).ok is True
    return account


def backfill(session: Session, *, apply: bool) -> Totals:
    return run(
        session,
        FixtureMt5Source(data(NOW_SERVER)),
        LATER,
        apply=apply,
        password_for=password,
    )


def test_dry_run_reports_and_writes_nothing(session: Session, synced: Account) -> None:
    totals = backfill(session, apply=False)

    assert totals.trades == 3
    assert totals.computed == 3
    assert any("MFE 1.0000 R, MAE 0.4000 R" in line for line in totals.lines)
    assert "пробний запуск" in summary(totals, apply=False)
    session.expire_all()
    assert trades_by_pid(session, synced.id)[SHORT_PID].excursion_status is None


def test_apply_stores_the_values(session: Session, synced: Account) -> None:
    backfill(session, apply=True)

    trade = trades_by_pid(session, synced.id)[SHORT_PID]
    assert (trade.excursion_status, str(trade.mfe_r)) == ("final", "1.0000")
    assert backfill(session, apply=False).trades == 0


def test_refuses_while_the_worker_syncs(session: Session, synced: Account) -> None:
    with pytest.raises(BackfillError, match="Стоп"):
        run(session, FixtureMt5Source(data(NOW_SERVER)), NOW, apply=True, password_for=password)


def test_refuses_during_the_idle_interval_too(session: Session, synced: Account) -> None:
    # outside trading hours the worker syncs every 15 min: 10 min ago it may still run
    with pytest.raises(BackfillError):
        run(
            session,
            FixtureMt5Source(data(NOW_SERVER)),
            NOW + timedelta(minutes=10),
            apply=True,
            password_for=password,
        )


def test_account_filter_and_per_trade_failures(
    session: Session, synced: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.mt5.errors import Mt5Error, Mt5ErrorCode

    source = FixtureMt5Source(data(NOW_SERVER))
    real_ticks = source.ticks
    calls = {"n": 0}

    def flaky(*args: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "no history yet")
        return real_ticks(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(source, "ticks", flaky)
    assert (
        run(session, source, LATER, apply=False, account_id=999, password_for=password).trades == 0
    )
    totals = run(session, source, LATER, apply=False, account_id=synced.id, password_for=password)
    assert totals.trades == 3
    assert totals.failed == 1
    assert totals.computed == 2


def test_retry_unavailable_recomputes_trades_marked_unavailable(
    session: Session, synced: Account
) -> None:
    for trade in trades_by_pid(session, synced.id).values():
        trade.excursion_status = "unavailable"
    session.commit()

    assert backfill(session, apply=False).trades == 0
    totals = run(
        session,
        FixtureMt5Source(data(NOW_SERVER)),
        LATER,
        apply=True,
        retry_unavailable=True,
        password_for=password,
    )
    assert totals.computed == 3
    session.expire_all()
    assert trades_by_pid(session, synced.id)[SHORT_PID].excursion_status == "final"


def without_exit_ticks() -> dict[str, object]:
    from tests.test_excursions_sync import OPEN

    fixture = data(NOW_SERVER)
    long_close = OPEN + 3 * 3600 + 30
    ticks = fixture["tick_history"]["EURUSD"]
    fixture["tick_history"] = {
        "EURUSD": [t for t in ticks if t["time_msc"] < (long_close - 60) * 1000]
    }
    return fixture


@pytest.mark.parametrize(
    ("later", "kind", "stored"),
    [(timedelta(minutes=30), "retry", None), (timedelta(days=2), "unavailable", "unavailable")],
)
def test_dry_run_counts_exactly_what_apply_writes(
    session: Session, synced: Account, later: timedelta, kind: str, stored: str | None
) -> None:
    from tests.test_excursions_sync import LONG_PID

    when = NOW + later
    dry = run(
        session, FixtureMt5Source(without_exit_ticks()), when, apply=False, password_for=password
    )
    # both 3 h trades (long and short) close in the minute whose ticks are missing
    assert dry.counts[kind] == 2
    assert dry.computed == 1

    applied = run(
        session, FixtureMt5Source(without_exit_ticks()), when, apply=True, password_for=password
    )
    assert applied.counts == dry.counts
    session.expire_all()
    assert trades_by_pid(session, synced.id)[LONG_PID].excursion_status == stored


# -- fallback terminal (own terminal removed, e.g. an old challenge account) ------------

DEAD = "D:/MT5/old challenge/terminal64.exe"
DONOR_LOGIN = 7000001


class TerminalsByPath:
    """One fixture terminal per path; any other path fails like a removed terminal."""

    def __init__(self, terminals: dict[str, FixtureMt5Source]) -> None:
        self.terminals = terminals
        self.current: FixtureMt5Source | None = None
        self.connects: list[tuple[str, int, str]] = []
        self.shutdowns = 0

    def connect(
        self,
        terminal_path: str,
        login: int,
        password: object,
        server: str,
        timeout_s: float = 60.0,
    ) -> object:
        from app.mt5.errors import Mt5Error, Mt5ErrorCode
        from app.mt5.source import require_password

        self.connects.append((terminal_path, login, server))
        require_password(login, password)  # type: ignore[arg-type]  # like the real source
        found = self.terminals.get(terminal_path)
        if found is None:
            raise Mt5Error(Mt5ErrorCode.TERMINAL_NOT_FOUND, f"terminal not found: {terminal_path}")
        info = found.connect(terminal_path, login, password, server, timeout_s)  # type: ignore[arg-type]
        self.current = found
        return info

    def shutdown(self) -> None:
        self.shutdowns += 1
        if self.current is not None:
            self.current.shutdown()
        self.current = None

    def _connected(self) -> FixtureMt5Source:
        assert self.current is not None, "read without a connected terminal"
        return self.current

    # PriceHistory is checked statically (no __getattr__): the two reads are explicit
    def ticks(self, symbol: str, lo: int, hi: int) -> object:
        return self._connected().ticks(symbol, lo, hi)

    def rates_m1(self, symbol: str, lo: int, hi: int) -> object:
        return self._connected().rates_m1(symbol, lo, hi)

    def __getattr__(self, name: str) -> object:  # other reads go to the connected terminal
        return getattr(self._connected(), name)


def terminal_of(
    login: int, server: str = "FundedNext-Server", *, symbol: bool = True, history: bool = True
) -> FixtureMt5Source:
    fixture = data(NOW_SERVER)
    fixture["account"] = fixture["account"] | {"login": login, "server": server}
    if not symbol:
        fixture["symbols"] = []
    if not symbol or not history:
        fixture["tick_history"], fixture["m1_rates"] = {}, {}
    return FixtureMt5Source(fixture)


def donor(session: Session, path: str, login: int = DONOR_LOGIN, **kw: Any) -> Account:
    from tests.test_sync import add_account

    return add_account(session, login, terminal_path=path, **kw)


@pytest.fixture
def removed(session: Session, synced: Account) -> Account:
    """The synced account was passed and its terminal folder deleted."""
    synced.terminal_path = DEAD
    synced.status = "passed"
    session.commit()
    return synced


def test_reads_history_from_another_terminal_of_the_same_server(
    session: Session, removed: Account
) -> None:
    donor(session, "D:/MT5/funded/terminal64.exe", name="FN Funded")
    source = TerminalsByPath({"D:/MT5/funded/terminal64.exe": terminal_of(DONOR_LOGIN)})

    totals = run(session, source, LATER, apply=True, password_for=password)  # type: ignore[arg-type]

    assert totals.computed == 3
    assert totals.failed == 0
    # own terminal first, then the donor with ITS OWN login: never another account's login
    assert source.connects == [
        (DEAD, removed.login, removed.server),
        ("D:/MT5/funded/terminal64.exe", DONOR_LOGIN, "FundedNext-Server"),
    ]
    # each result names the terminal and server it came from
    results = [line for line in totals.lines if line.startswith("#")]
    assert len(results) == 3
    assert all("FN Funded" in line and "FundedNext-Server" in line for line in results)
    session.expire_all()
    trade = trades_by_pid(session, removed.id)[SHORT_PID]
    assert (trade.excursion_status, str(trade.mfe_r)) == ("final", "1.0000")


def test_prefers_the_same_server_then_any_terminal_of_the_firm(
    session: Session, removed: Account
) -> None:
    donor(session, "D:/MT5/other server", DONOR_LOGIN + 1, server="FundedNext-Server 2")
    donor(session, "D:/MT5/other firm", DONOR_LOGIN + 2, firm="FTMO", server="FTMO-Server")
    donor(session, "D:/MT5/same server", DONOR_LOGIN + 3)
    source = TerminalsByPath(
        {
            "D:/MT5/other server": terminal_of(DONOR_LOGIN + 1, "FundedNext-Server 2"),
            "D:/MT5/other firm": terminal_of(DONOR_LOGIN + 2, "FTMO-Server"),
        }
    )  # the same-server terminal is gone too -> the other FundedNext server

    totals = run(session, source, LATER, apply=False, password_for=password)  # type: ignore[arg-type]

    assert [c[0] for c in source.connects] == [DEAD, "D:/MT5/same server", "D:/MT5/other server"]
    assert totals.computed == 3
    assert all("FundedNext-Server 2" in line for line in totals.lines if line.startswith("#"))


def test_no_usable_terminal_counts_failed_and_writes_nothing(
    session: Session, removed: Account
) -> None:
    donor(session, "D:/MT5/archived", status="archived")  # archived terminals are not used
    source = TerminalsByPath({"D:/MT5/archived": terminal_of(DONOR_LOGIN)})

    totals = run(session, source, LATER, apply=True, password_for=password)  # type: ignore[arg-type]

    assert [c[0] for c in source.connects] == [DEAD]
    assert totals.failed == 3
    assert any("terminal not found" in line for line in totals.lines)
    session.expire_all()
    assert trades_by_pid(session, removed.id)[SHORT_PID].excursion_status is None


def test_own_terminal_is_named_on_each_result(session: Session, synced: Account) -> None:
    totals = backfill(session, apply=False)

    results = [line for line in totals.lines if line.startswith("#")]
    assert results
    assert all(synced.name in line for line in results)


FUNDED = "D:/MT5/funded/terminal64.exe"
TWO_DAYS_LATER = NOW + timedelta(days=2)  # closed > 24 h ago: no history = «unavailable»


@pytest.mark.parametrize("donor_terminal", ["no symbol", "no history"])
def test_another_terminal_never_marks_a_trade_unavailable(
    session: Session, removed: Account, donor_terminal: str
) -> None:
    donor(session, FUNDED)
    terminal = terminal_of(
        DONOR_LOGIN, symbol=donor_terminal != "no symbol", history=donor_terminal != "no history"
    )
    source = TerminalsByPath({FUNDED: terminal})

    totals = run(session, source, TWO_DAYS_LATER, apply=True, password_for=password)  # type: ignore[arg-type]

    assert totals.failed == 3
    assert totals.counts["unavailable"] == 0
    session.expire_all()
    assert {t.excursion_status for t in trades_by_pid(session, removed.id).values()} == {None}


def test_read_error_on_another_terminal_counts_once_and_stores_nothing(
    session: Session, removed: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.mt5.errors import Mt5Error, Mt5ErrorCode

    donor(session, FUNDED)
    terminal = terminal_of(DONOR_LOGIN)

    def broken(_: str) -> None:
        raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "symbol_info failed")

    monkeypatch.setattr(terminal, "symbol_spec", broken)
    source = TerminalsByPath({FUNDED: terminal})

    totals = run(session, source, LATER, apply=True, password_for=password)  # type: ignore[arg-type]

    assert totals.trades == 3
    assert totals.failed == 3
    assert sum(totals.counts.values()) == 3
    session.expire_all()
    assert trades_by_pid(session, removed.id)[SHORT_PID].excursion_status is None


def test_skips_a_terminal_without_password_and_always_shuts_down(
    session: Session, removed: Account
) -> None:
    from pydantic import SecretStr

    donor(session, "D:/MT5/no password", DONOR_LOGIN + 9)
    donor(session, FUNDED)
    source = TerminalsByPath(
        {"D:/MT5/no password": terminal_of(DONOR_LOGIN + 9), FUNDED: terminal_of(DONOR_LOGIN)}
    )

    def only_some(login: int) -> SecretStr | None:
        return None if login == DONOR_LOGIN + 9 else SecretStr("not-a-real-secret")

    totals = run(session, source, LATER, apply=False, password_for=only_some)  # type: ignore[arg-type]

    assert [c[0] for c in source.connects] == [DEAD, "D:/MT5/no password", FUNDED]
    assert totals.computed == 3
    assert source.shutdowns == len(source.connects)  # after every refused and the used one

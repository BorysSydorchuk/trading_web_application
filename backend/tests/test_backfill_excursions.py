"""M8-16 backfill tool: dry run prints and writes nothing, --apply stores, refuses while
the worker syncs (fixture MT5 source, same data as test_excursions_sync)."""

# ruff: noqa: F811  (pytest fixtures imported from test_excursions_sync)
from __future__ import annotations

from datetime import timedelta

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

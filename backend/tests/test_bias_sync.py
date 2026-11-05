"""The MT5 sync assigns bias alignment to synced trades (M4-04)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import BiasEntry, BiasNote
from app.models.enums import BiasKind
from tests.services.test_bias_alignment_service import truncate_all
from tests.test_sync import WEEK_LOGIN, WEEK_NOW, add_account, run, source, trades_by_pid

MONDAY = date(2026, 10, 19)  # week of the basic_week fixture


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    truncate_all(db_engine)
    yield
    truncate_all(db_engine)


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


def test_sync_assigns_alignment(session: Session, rules: RulesConfig) -> None:
    weekly = BiasNote(kind=BiasKind.WEEKLY.value, period_date=MONDAY)
    weekly.entries = [
        BiasEntry(symbol=s, direction="bullish") for s in ("EURUSD", "GBPUSD", "XAUUSD", "GER40")
    ]
    daily = BiasNote(kind=BiasKind.PRE_LONDON.value, period_date=MONDAY)
    daily.entries = [BiasEntry(symbol="EURUSD", direction="neutral")]
    session.add_all([weekly, daily])
    session.commit()

    account = add_account(session, WEEK_LOGIN)
    log = run(session, account, source("basic_week.json"), rules, WEEK_NOW)
    assert log.ok is True, log.error_message

    trades = trades_by_pid(session, account.id).values()
    assert trades
    for t in trades:
        expected_weekly = "aligned" if t.direction == "buy" else "counter"
        assert t.bias_alignment_weekly == expected_weekly, t.position_id
        assert t.bias_alignment_monthly == "no_bias", t.position_id
        assert t.bias_alignment is not None, t.position_id
    t1 = trades_by_pid(session, account.id)[2000101]  # Monday 09:30 Brussels
    assert t1.symbol == "EURUSD"
    assert t1.bias_alignment == "neutral_bias"


def test_sync_keeps_override(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN)
    assert run(session, account, source("basic_week.json"), rules, WEEK_NOW).ok is True
    t1 = trades_by_pid(session, account.id)[2000101]  # EURUSD, Monday 09:30 Brussels
    assert t1.bias_alignment == "no_bias"
    t1.bias_alignment = None  # outside the second sync's window: realigned by the backfill
    t1.bias_alignment_override = "aligned"
    t1.bias_alignment_override_reason = "свій план"
    note = BiasNote(kind=BiasKind.PRE_LONDON.value, period_date=MONDAY)
    note.entries = [BiasEntry(symbol="EURUSD", direction="neutral")]
    session.add(note)
    session.commit()

    assert run(session, account, source("basic_week.json"), rules, WEEK_NOW).ok is True
    t1 = trades_by_pid(session, account.id)[2000101]
    assert t1.bias_alignment == "neutral_bias"  # auto value recomputed by the sync
    assert (t1.bias_alignment_override, t1.bias_alignment_override_reason) == (
        "aligned",
        "свій план",
    )

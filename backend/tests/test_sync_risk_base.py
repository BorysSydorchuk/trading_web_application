"""M5-10: the sync computes risk % and P&L % of new trades with the account size.

The account size is ``accounts.reference_balance`` (default = starting_balance). The live balance
only feeds ``balance_at_open`` (information). Uses the basic_week fixture of test_sync.py:
trade 2000301 risks 500.00 and opened at balance 100628.00; trade 2000101 netted 284.00.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import RuleViolation
from tests.test_sync import WEEK_LOGIN, WEEK_NOW, add_account, run, source, trades_by_pid

D = Decimal


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
    factory: sessionmaker[Session] = make_session_factory(db_engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def rules() -> RulesConfig:
    return get_rules()


def test_percents_use_the_stored_account_size(session: Session, rules: RulesConfig) -> None:
    account = add_account(session, WEEK_LOGIN, reference_balance=D("50000.00"))

    log = run(session, account, source("basic_week.json"), rules, WEEK_NOW)

    assert log.ok is True, log.error_message
    trades = trades_by_pid(session, account.id)
    assert trades[2000301].risk_pct == D("1.0000")  # 500.00 / 50000, not / 100628
    assert trades[2000101].pnl_pct == D("0.5680")  # 284.00 / 50000
    assert trades[2000301].balance_at_open == D("100628.00")  # still stored
    assert trades[2000701].pnl_pct is None  # open position


def test_an_account_created_without_a_size_uses_its_starting_balance(
    session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, WEEK_LOGIN)  # starting_balance 100000.00, no size given

    assert account.reference_balance == D("100000.00")  # ORM insert default (M5-10)
    run(session, account, source("basic_week.json"), rules, WEEK_NOW)

    assert trades_by_pid(session, account.id)[2000301].risk_pct == D("0.5000")


@pytest.mark.parametrize(
    ("size", "pct", "flagged"),
    [("20000.00", "2.5000", True), ("50000.00", "1.0000", False)],
)
def test_max_risk_is_flagged_only_when_the_percent_of_the_size_exceeds_the_limit(
    session: Session, rules: RulesConfig, size: str, pct: str, flagged: bool
) -> None:
    # 500.00 risk: 2.5 % of 20000 (over the 1.1 % limit) but 1.0000 % of 50000 (ok).
    account = add_account(session, WEEK_LOGIN, reference_balance=D(size))

    run(session, account, source("basic_week.json"), rules, WEEK_NOW)

    trade = trades_by_pid(session, account.id)[2000301]
    max_risk_trade_ids = set(
        session.scalars(
            select(RuleViolation.trade_id).where(RuleViolation.rule_key == "max_risk_pct")
        )
    )
    assert trade.risk_pct == D(pct)
    assert (trade.id in max_risk_trade_ids) is flagged

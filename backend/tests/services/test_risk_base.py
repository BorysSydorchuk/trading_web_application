"""M5-10 recompute: ``app.services.risk_base`` (new module, names fixed by these tests).

- ``recompute_account(db: Session, account_id: int) -> int``: sets risk_pct = risk_amount /
  size x 100 and pnl_pct = net_pnl / size x 100 (closed trades only; 4 dp half-up; NULL stays
  NULL) for every trade of the account, then recomputes auto rule violations of all of the
  account's trades (``get_rules()``). Flushes, does not commit. Returns the trade count.
- ``recompute_all(session_factory: sessionmaker[Session]) -> int | None``: its own session and
  transaction (commits), recompute_account for every account in its own savepoint: a failing
  account is logged at ERROR (with its id) and skipped, the others are still committed. Returns
  the trade count of the accounts that succeeded; None (ERROR logged) only when the whole step
  fails (DB down, broken rules.yaml). Never raises. Idempotent.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config_files.loader import ConfigError
from app.db import make_session_factory
from app.models import Account, RuleViolation, Trade
from app.services import risk_base
from app.services.risk_base import recompute_account, recompute_all

D = Decimal
MON = datetime(2026, 11, 2, 7, 5, tzinfo=UTC)
STALE = D("9.9999")


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


def make_account(db: Session, login: int, size: str) -> Account:
    account = Account(
        name=f"recompute {login}",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase="phase_1",
        login=login,
        server="FundedNext-Server",
        starting_balance=D("100000"),
        currency="USD",
        reference_balance=D(size),
    )
    db.add(account)
    db.commit()
    return account


def make_trades(db: Session, account: Account, base: int) -> list[Trade]:
    common: dict[str, Any] = {
        "account_id": account.id,
        "symbol": "XAUUSD",
        "broker_symbol": "XAUUSD",
        "direction": "buy",
        "entry_price": D("2650"),
        "volume": D("1"),
        "balance_at_open": D("10401.70"),
        "session": "london",
        "risk_amount": D("100.00"),
        "risk_pct": STALE,
    }
    rows = [
        Trade(
            **common,
            position_id=base,
            open_time=MON,
            close_time=MON + timedelta(minutes=20),
            net_pnl=D("-300.00"),
            pnl_pct=STALE,
            status="needs_description",
        ),
        Trade(
            **common,
            position_id=base + 1,
            open_time=MON + timedelta(hours=2),
            status="open",
        ),
        Trade(  # no risk: percent stays NULL
            **(common | {"risk_amount": None, "risk_pct": None}),
            position_id=base + 2,
            open_time=MON + timedelta(days=1),
            close_time=MON + timedelta(days=1, minutes=5),
            net_pnl=D("50.00"),
            pnl_pct=None,
            status="needs_sl",
        ),
    ]
    db.add_all(rows)
    db.commit()
    return rows


def reload(db: Session, trade: Trade) -> Trade:
    db.expire_all()
    return db.get_one(Trade, trade.id)


def keys(db: Session, trade: Trade) -> set[str]:
    db.expire_all()
    return {
        v.rule_key
        for v in db.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade.id))
    }


def test_recompute_account_updates_percents_and_violations(session: Session) -> None:
    account = make_account(session, 71001, "10000.00")
    closed, entry, no_risk = make_trades(session, account, 1)

    count = recompute_account(session, account.id)
    session.commit()

    assert count == 3
    assert reload(session, closed).risk_pct == D("1.0000")
    assert reload(session, closed).pnl_pct == D("-3.0000")
    assert reload(session, entry).risk_pct == D("1.0000")
    assert reload(session, entry).pnl_pct is None
    assert reload(session, no_risk).risk_pct is None
    assert reload(session, no_risk).pnl_pct == D("0.5000")
    assert "daily_stop_loss_pct" in keys(session, entry)  # -300.00 = -3.00 % of 10000


def test_recompute_account_leaves_other_accounts_alone(session: Session) -> None:
    mine = make_account(session, 71001, "10000.00")
    other = make_account(session, 71002, "10000.00")
    make_trades(session, mine, 1)
    other_closed, other_entry, _ = make_trades(session, other, 10)

    recompute_account(session, mine.id)
    session.commit()

    assert reload(session, other_closed).risk_pct == STALE
    assert keys(session, other_entry) == set()


def test_recompute_all_covers_every_account_and_is_idempotent(
    factory: sessionmaker[Session], session: Session
) -> None:
    a = make_account(session, 71001, "10000.00")
    b = make_account(session, 71002, "20000.00")
    a_closed, a_entry, _ = make_trades(session, a, 1)
    b_closed, b_entry, _ = make_trades(session, b, 10)

    def snapshot() -> tuple[Any, ...]:
        return (
            reload(session, a_closed).risk_pct,
            reload(session, b_closed).risk_pct,
            keys(session, a_entry),
            keys(session, b_entry),
        )

    first = recompute_all(factory)
    after_first = snapshot()
    second = recompute_all(factory)

    assert first == 6
    assert second == 6
    assert after_first[:2] == (D("1.0000"), D("0.5000"))
    assert "daily_stop_loss_pct" in after_first[2]  # -3.00 % of 10000
    assert "daily_stop_loss_pct" not in after_first[3]  # -1.50 % of 20000
    assert snapshot() == after_first


def test_recompute_all_without_accounts_is_zero(factory: sessionmaker[Session]) -> None:
    assert recompute_all(factory) == 0


def test_recompute_all_never_raises_and_returns_none_on_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> Any:
        raise RuntimeError("db down")

    with caplog.at_level("ERROR"):
        result = recompute_all(broken)  # type: ignore[arg-type]

    assert result is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_recompute_all_skips_a_failing_account_and_commits_the_others(
    factory: sessionmaker[Session], session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    # -300.00 / 0.01 x 100 = -3 000 000 % overflows NUMERIC(10,4): that account fails.
    bad = make_account(session, 71001, "0.01")
    good = make_account(session, 71002, "20000.00")
    bad_closed, _, _ = make_trades(session, bad, 1)
    good_closed, good_entry, _ = make_trades(session, good, 10)

    with caplog.at_level("ERROR"):
        result = recompute_all(factory)

    assert result == 3  # the good account's trades only
    assert reload(session, bad_closed).risk_pct == STALE
    assert reload(session, good_closed).risk_pct == D("0.5000")
    assert reload(session, good_closed).pnl_pct == D("-1.5000")
    assert keys(session, good_entry) == set()  # -1.50 % of 20000: no daily stop
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any(str(bad.id) in r.getMessage() for r in errors)


def test_recompute_all_with_a_broken_rules_yaml_is_none_and_changes_nothing(
    factory: sessionmaker[Session],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = make_account(session, 71001, "10000.00")
    closed, _, _ = make_trades(session, account, 1)

    def broken() -> Any:
        raise ConfigError(Path("rules.yaml"), ["broken"])

    monkeypatch.setattr(risk_base, "get_rules", broken)

    with caplog.at_level("ERROR"):
        result = recompute_all(factory)

    assert result is None
    assert reload(session, closed).risk_pct == STALE
    assert any(r.levelname == "ERROR" for r in caplog.records)

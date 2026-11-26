"""`firm_daily_loss` through ``recompute_rules`` (stored trades, docs/api.md "Firm rules
from config: KeyFunding"). Firm day = server day; server offset 0 here (UTC midnight)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.models import Account, RuleViolation, Trade
from app.services.trade_rules import recompute_rules

D = Decimal
KEY = "firm_daily_loss"


def _account(db: Session, firm: str, login: int, offset: int | None = 0) -> Account:
    account = Account(
        name=f"{firm} {login}",
        firm=firm,
        program="Program",
        phase="phase_1",
        login=login,
        server="Server",
        starting_balance=D("10000"),
        currency="USD",
        reference_balance=D("10000"),
        server_offset_hours=offset,
    )
    db.add(account)
    db.flush()
    return account


_PIDS = iter(range(5000, 90000))


def _trade(
    db: Session, account: Account, opened: datetime, pnl: str | None, hours: int = 1
) -> Trade:
    closed = pnl is not None
    row = Trade(
        account_id=account.id,
        position_id=next(_PIDS),
        symbol="XAUUSD",
        broker_symbol="XAUUSD",
        direction="buy",
        open_time=opened,
        close_time=opened + timedelta(hours=hours) if closed else None,
        entry_price=D("2650"),
        volume=D("1"),
        net_pnl=D(pnl) if pnl is not None else None,
        balance_at_open=D("10000"),
        status="needs_description" if closed else "open",
    )
    db.add(row)
    db.flush()
    return row


def _keys(db: Session, trade_id: int) -> set[str]:
    db.expire_all()
    rows = db.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade_id))
    return {r.rule_key for r in rows}


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def test_entry_after_the_firm_daily_loss_gets_the_violation(db_session: Session) -> None:
    account = _account(db_session, "KeyFunding", 1)
    loser = _trade(db_session, account, _at(12, 1), "-450")
    entry = _trade(db_session, account, _at(12, 8), "20")

    recompute_rules(db_session, account.id, _at(12, 1), get_rules())

    assert KEY not in _keys(db_session, loser.id)
    assert KEY in _keys(db_session, entry.id)


def test_firm_name_variants_match(db_session: Session) -> None:
    account = _account(db_session, "Key Funding", 2)
    _trade(db_session, account, _at(12, 1), "-450")
    entry = _trade(db_session, account, _at(12, 8), "20")

    recompute_rules(db_session, account.id, _at(12, 1), get_rules())

    assert KEY in _keys(db_session, entry.id)


def test_the_violation_does_not_cross_the_reset(db_session: Session) -> None:
    account = _account(db_session, "KeyFunding", 3)
    _trade(db_session, account, _at(12, 20), "-450")
    same_day = _trade(db_session, account, _at(12, 23, 30), "5")
    next_day = _trade(db_session, account, _at(13, 0, 30), "5")

    recompute_rules(db_session, account.id, _at(12, 20), get_rules())

    assert KEY in _keys(db_session, same_day.id)
    assert KEY not in _keys(db_session, next_day.id)


def test_server_offset_moves_the_reset(db_session: Session) -> None:
    account = _account(db_session, "KeyFunding", 4, offset=2)  # reset 22:00 UTC
    _trade(db_session, account, _at(12, 19), "-450")  # closes 20:00 UTC
    before = _trade(db_session, account, _at(12, 21, 30), "5")
    after = _trade(db_session, account, _at(12, 22, 30), "5")

    recompute_rules(db_session, account.id, _at(12, 19), get_rules())

    assert KEY in _keys(db_session, before.id)
    assert KEY not in _keys(db_session, after.id)


def test_a_firm_day_that_started_before_the_brussels_monday_is_covered(
    db_session: Session,
) -> None:
    """Entry Mon 2026-11-09 00:30 Brussels (= Sun 23:30 UTC) is in the firm day that began
    Sun 00:00 UTC; the loss closed Sun 20:00 UTC, before the Brussels Monday starts."""
    account = _account(db_session, "KeyFunding", 5)
    _trade(db_session, account, _at(8, 19), "-450")
    entry = _trade(db_session, account, _at(8, 23, 30), "5")

    recompute_rules(db_session, account.id, _at(8, 23, 30), get_rules())

    assert KEY in _keys(db_session, entry.id)


def test_fundednext_never_gets_the_firm_violation(db_session: Session) -> None:
    account = _account(db_session, "FundedNext", 6)
    _trade(db_session, account, _at(12, 1), "-900")
    entry = _trade(db_session, account, _at(12, 8), "20")

    recompute_rules(db_session, account.id, _at(12, 1), get_rules())

    assert KEY not in _keys(db_session, entry.id)


def test_recompute_is_idempotent_and_removes_a_stale_violation(db_session: Session) -> None:
    account = _account(db_session, "KeyFunding", 7)
    loser = _trade(db_session, account, _at(12, 1), "-450")
    entry = _trade(db_session, account, _at(12, 8), "20")
    recompute_rules(db_session, account.id, _at(12, 1), get_rules())
    recompute_rules(db_session, account.id, _at(12, 1), get_rules())
    assert KEY in _keys(db_session, entry.id)

    loser.net_pnl = D("-100")
    db_session.flush()
    recompute_rules(db_session, account.id, _at(12, 1), get_rules())

    assert KEY not in _keys(db_session, entry.id)


def test_an_account_edit_of_daily_loss_changes_the_limit(db_session: Session) -> None:
    account = _account(db_session, "KeyFunding", 8)
    account.daily_loss_pct = D("5")
    _trade(db_session, account, _at(12, 1), "-450")
    entry = _trade(db_session, account, _at(12, 8), "20")

    recompute_rules(db_session, account.id, _at(12, 1), get_rules())

    assert KEY not in _keys(db_session, entry.id)  # -4.5 % is inside the account's own 5 %

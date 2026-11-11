"""M5-10: auto violations of stored trades use the account size (``accounts.reference_balance``).

``app.services.trade_rules.recompute_rules`` builds each ``RuleTradeInput`` with the trade's
account size, so daily/weekly stops ignore ``balance_at_open`` / the period start balance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.models import Account, RuleViolation, Trade
from app.services.trade_rules import recompute_rules

D = Decimal
MON = datetime(2026, 11, 2, 7, 5, tzinfo=UTC)  # Mon 08:05 Brussels, london


def _account(db: Session, size: str, login: int = 61001) -> Account:
    account = Account(
        name=f"risk base {login}",
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
    db.flush()
    return account


def _trade(
    db: Session, account: Account, pid: int, open_at: datetime, net: str | None, **kw: object
) -> Trade:
    closed = net is not None
    values: dict[str, object] = {
        "account_id": account.id,
        "position_id": pid,
        "symbol": "XAUUSD",
        "broker_symbol": "XAUUSD",
        "direction": "buy",
        "open_time": open_at,
        "close_time": open_at + timedelta(minutes=20) if closed else None,
        "entry_price": D("2650"),
        "volume": D("1"),
        "net_pnl": D(net) if net is not None else None,
        "balance_at_open": D("10401.70"),  # never the base (M5-10)
        "session": "london",
        "status": "needs_description" if closed else "open",
    }
    row = Trade(**(values | kw))
    db.add(row)
    db.flush()
    return row


def _keys(db: Session, trade: Trade) -> set[str]:
    db.expire_all()
    rows = db.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade.id))
    return {r.rule_key for r in rows}


def _day(db: Session, size: str, loss: str) -> tuple[Account, Trade]:
    account = _account(db, size)
    _trade(db, account, 1, MON, loss)
    entry = _trade(db, account, 2, MON + timedelta(hours=2), None)
    recompute_rules(db, account.id, MON, get_rules())
    return account, entry


def test_daily_stop_minus_300_on_a_10000_size_flags_the_next_entry(db_session: Session) -> None:
    _, entry = _day(db_session, "10000", "-300.00")

    assert "daily_stop_loss_pct" in _keys(db_session, entry)


def test_daily_stop_minus_299_99_does_not(db_session: Session) -> None:
    _, entry = _day(db_session, "10000", "-299.99")

    assert "daily_stop_loss_pct" not in _keys(db_session, entry)


def test_the_same_loss_on_a_bigger_size_is_not_a_stop(db_session: Session) -> None:
    _, entry = _day(db_session, "100000", "-300.00")

    assert "daily_stop_loss_pct" not in _keys(db_session, entry)


def test_weekly_stop_and_profit_stop_use_the_size(db_session: Session) -> None:
    account = _account(db_session, "10000", login=61002)
    _trade(db_session, account, 1, MON, "-600.00")  # Mon: -6.00 %
    wed = _trade(db_session, account, 2, MON + timedelta(days=2), None)
    win = _account(db_session, "10000", login=61003)
    _trade(db_session, win, 3, MON, "1000.00")
    wed_win = _trade(db_session, win, 4, MON + timedelta(days=2), None)

    recompute_rules(db_session, account.id, MON, get_rules())
    recompute_rules(db_session, win.id, MON, get_rules())

    assert "weekly_stop_loss_pct" in _keys(db_session, wed)
    assert "weekly_stop_profit_pct" in _keys(db_session, wed_win)


def test_max_risk_pct_uses_the_stored_risk_pct(db_session: Session) -> None:
    account = _account(db_session, "10000", login=61004)
    flagged = _trade(db_session, account, 1, MON, "10.00", risk_pct=D("1.1001"))
    fine = _trade(db_session, account, 2, MON + timedelta(days=1), "10.00", risk_pct=D("1.1000"))

    recompute_rules(db_session, account.id, MON, get_rules())

    assert "max_risk_pct" in _keys(db_session, flagged)
    assert "max_risk_pct" not in _keys(db_session, fine)

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.rules import Violation
from app.models import Account, RuleViolation, Trade
from app.models.enums import AccountPhase, Direction, ViolationSource
from app.services.violations import apply_auto_violations


def _trade(session: Session) -> Trade:
    account = Account(
        name="FN violations test",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase=AccountPhase.PHASE_1,
        login=7001,
        server="FundedNext-Server",
        starting_balance=Decimal("100000.00"),
        currency="USD",
    )
    session.add(account)
    session.flush()
    trade = Trade(
        account_id=account.id,
        position_id=1,
        symbol="XAUUSD",
        direction=Direction.BUY,
        open_time=datetime(2026, 11, 2, 8, tzinfo=UTC),
        close_time=datetime(2026, 11, 2, 9, tzinfo=UTC),
        entry_price=Decimal("2650"),
        volume=Decimal("0.5"),
    )
    session.add(trade)
    session.flush()
    return trade


def _rows(session: Session, trade_id: int) -> dict[str, tuple[str, str | None]]:
    rows = session.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade_id))
    return {r.rule_key: (r.source, r.details) for r in rows}


def test_apply_is_idempotent_and_keeps_user_rows(db_session: Session) -> None:
    trade = _trade(db_session)
    db_session.add_all(
        [
            RuleViolation(trade_id=trade.id, rule_key="followed_plan", source=ViolationSource.USER),
            RuleViolation(
                trade_id=trade.id,
                rule_key="entry_session",
                source=ViolationSource.USER,
                details="my note",
            ),
        ]
    )
    db_session.flush()

    first = [
        Violation("max_risk_pct", "risk 1.26% > limit 1.1%"),
        Violation("entry_session", "entry in session premarket (not allowed)"),
        Violation("min_planned_rr", "planned RR 1.20 < minimum 1.5"),
    ]
    apply_auto_violations(db_session, trade.id, first)
    apply_auto_violations(db_session, trade.id, first)
    assert _rows(db_session, trade.id) == {
        "followed_plan": ("user", None),
        "entry_session": ("user", "my note"),  # user row wins, untouched
        "max_risk_pct": ("auto", "risk 1.26% > limit 1.1%"),
        "min_planned_rr": ("auto", "planned RR 1.20 < minimum 1.5"),
    }

    # Recompute: one auto violation gone, one with new details.
    apply_auto_violations(
        db_session, trade.id, [Violation("max_risk_pct", "risk 1.30% > limit 1.1%")]
    )
    db_session.expire_all()
    assert _rows(db_session, trade.id) == {
        "followed_plan": ("user", None),
        "entry_session": ("user", "my note"),
        "max_risk_pct": ("auto", "risk 1.30% > limit 1.1%"),
    }

    apply_auto_violations(db_session, trade.id, [])
    db_session.expire_all()
    assert set(_rows(db_session, trade.id)) == {"followed_plan", "entry_session"}

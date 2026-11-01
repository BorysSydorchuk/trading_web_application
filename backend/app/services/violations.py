"""Persist rules-engine results (DECISIONS 2026-11-01: auto violations recomputed, user kept)."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.rules import Violation
from app.models import RuleViolation
from app.models.enums import ViolationSource


def apply_auto_violations(session: Session, trade_id: int, violations: Iterable[Violation]) -> None:
    """Make the trade's ``source=auto`` rows equal ``violations``; idempotent, flushes only.

    ``source=user`` rows are never modified or deleted. If the user already recorded the same
    rule_key, that row stays as is and no auto row is added (one row per trade + rule_key).
    """
    wanted: dict[str, str] = {}
    for violation in violations:
        wanted.setdefault(violation.rule_key, violation.details)
    rows = session.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade_id)).all()
    by_key = {row.rule_key: row for row in rows}

    for row in rows:
        if row.source == ViolationSource.AUTO and row.rule_key not in wanted:
            session.delete(row)
    for rule_key, details in wanted.items():
        current = by_key.get(rule_key)
        if current is None:
            session.add(
                RuleViolation(
                    trade_id=trade_id,
                    rule_key=rule_key,
                    source=ViolationSource.AUTO,
                    details=details,
                )
            )
        elif current.source == ViolationSource.AUTO and current.details != details:
            current.details = details
    session.flush()

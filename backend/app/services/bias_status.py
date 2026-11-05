"""Dashboard bias reminders (docs/api.md M4 "Bias status"; DECISIONS 2026-11-05).

`remind` = a weekday, Brussels now within the bias.yaml window [from, until) and no note
of that kind for today. Weekly / monthly: the note of the current week / month, if any.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.config_files.bias import BiasConfig
from app.domain.bias_alignment import DAILY_KINDS, month_start, week_start
from app.domain.sessions import DEFAULT_TZ, to_local
from app.models import BiasNote
from app.models.enums import BiasKind
from app.schemas.bias import BiasPeriodStatus, BiasSessions, BiasSessionStatus, BiasStatus

WEEKDAYS = range(5)  # Monday..Friday


def bias_status(db: Session, config: BiasConfig, now: datetime) -> BiasStatus:
    local = to_local(now, DEFAULT_TZ)
    today = local.date()
    wall = local.time().replace(tzinfo=None)
    weekday = local.weekday() in WEEKDAYS
    periods = {
        BiasKind.PRE_LONDON: today,
        BiasKind.PRE_NY: today,
        BiasKind.WEEKLY: week_start(today),
        BiasKind.MONTHLY: month_start(today),
    }
    rows = db.execute(
        select(BiasNote.kind, BiasNote.id).where(
            tuple_(BiasNote.kind, BiasNote.period_date).in_(
                [(k.value, d) for k, d in periods.items()]
            )
        )
    )
    note_ids: dict[str, int] = {row.kind: row.id for row in rows}

    sessions: dict[str, BiasSessionStatus] = {}
    for kind in DAILY_KINDS:
        window = config.reminder(kind)
        if window is None:  # pragma: no cover - daily kinds always have a window
            raise ValueError(f"no reminder window for {kind}")
        note_id = note_ids.get(kind.value)
        hours = window.to_api()
        sessions[kind.value] = BiasSessionStatus(
            note_id=note_id,
            missing=note_id is None,
            remind=weekday and note_id is None and window.contains(wall),
            start=hours["from"],
            until=hours["until"],
        )
    return BiasStatus(
        today=today,
        weekday=weekday,
        now=now,
        sessions=BiasSessions.model_validate(sessions),
        weekly=BiasPeriodStatus(note_id=note_ids.get(BiasKind.WEEKLY.value)),
        monthly=BiasPeriodStatus(note_id=note_ids.get(BiasKind.MONTHLY.value)),
    )

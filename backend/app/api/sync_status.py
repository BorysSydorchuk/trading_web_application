"""GET /api/sync/status: one row per non-archived account, from the worker's sync_log."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.config_files import ConfigError, get_rules
from app.db import get_db
from app.domain.sessions import is_trading_time
from app.models import Account, SyncLog
from app.models.enums import AccountStatus
from app.schemas.sync_status import AccountSyncStatus, SyncState, SyncStatusList

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])

STALE_FACTOR = 3
# Used only when config/rules.yaml is broken: the idle interval avoids false "stale".
FALLBACK_INTERVAL_S = 900


def utc_now() -> datetime:
    """Dependency so tests can pin the clock."""
    return datetime.now(UTC)


def expected_interval(at: datetime) -> timedelta:
    """Worker cadence that applies at `at` (PRD 6.2, rules.yaml `sync`)."""
    try:
        rules = get_rules()
    except ConfigError as exc:
        logger.error(
            "Sync status uses a %s s interval, rules.yaml is invalid: %s", FALLBACK_INTERVAL_S, exc
        )
        return timedelta(seconds=FALLBACK_INTERVAL_S)
    sync = rules.sync
    trading = is_trading_time(
        at, sync.trading_days, sync.trading_hours.start, sync.trading_hours.end, rules.timezone
    )
    seconds = sync.interval_trading_seconds if trading else sync.interval_idle_seconds
    return timedelta(seconds=seconds)


def stale_after(now: datetime, last_attempt: datetime) -> timedelta:
    """3x the longer of the interval now and at the last attempt: the worker scheduled its
    next run with the interval that applied then (e.g. a 15-min idle gap right at 08:00)."""
    return STALE_FACTOR * max(expected_interval(now), expected_interval(last_attempt))


def sync_state(latest: SyncLog | None, now: datetime) -> SyncState:
    """never | running | error | ok while the worker is active; stale once nothing (not
    even a failed or running attempt) happened for 3x the expected interval."""
    if latest is None:
        return "never"
    last_attempt = latest.finished_at or latest.started_at
    if now - last_attempt > stale_after(now, last_attempt):
        return "stale"
    if latest.ok is None:
        return "running"
    return "ok" if latest.ok else "error"


@router.get("/status", response_model=SyncStatusList)
def sync_status(db: Session = Depends(get_db), now: datetime = Depends(utc_now)) -> SyncStatusList:
    accounts = db.scalars(
        select(Account)
        .where(Account.status != AccountStatus.ARCHIVED.value)
        .order_by(func.lower(Account.name), Account.id)
    ).all()
    ids = [a.id for a in accounts]
    newest_first = (SyncLog.account_id, SyncLog.started_at.desc(), SyncLog.id.desc())
    latest = {
        row.account_id: row
        for row in db.scalars(
            select(SyncLog)
            .where(SyncLog.account_id.in_(ids))
            .ext(distinct_on(SyncLog.account_id))
            .order_by(*newest_first)
        )
    }
    last_ok = {
        row.account_id: row
        for row in db.scalars(
            select(SyncLog)
            .where(SyncLog.account_id.in_(ids), SyncLog.ok.is_(True))
            .ext(distinct_on(SyncLog.account_id))
            .order_by(*newest_first)
        )
    }

    items: list[AccountSyncStatus] = []
    for account in accounts:
        row = latest.get(account.id)
        success = last_ok.get(account.id)
        failed = row is not None and row.ok is False
        items.append(
            AccountSyncStatus(
                account_id=account.id,
                account_name=account.name,
                state=sync_state(row, now),
                last_attempt_utc=row.started_at if row is not None else None,
                last_success_utc=(success.finished_at or success.started_at) if success else None,
                error_code=row.error_code if failed and row is not None else None,
                error_message=row.error_message if failed and row is not None else None,
                server_offset_hours=account.server_offset_hours,
                # Only a successful sync knows the positions; a running row has no count yet.
                open_positions=success.open_positions if success is not None else 0,
            )
        )
    return SyncStatusList(items=items)

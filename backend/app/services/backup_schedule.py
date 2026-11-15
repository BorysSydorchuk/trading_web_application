"""One latest Brussels schedule, durable claims, bounded retries and crash reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from app.services.backup_state import (
    ErrorCode,
    ScheduleState,
    read_state,
    schedule_lock,
    write_state,
)
from app.services.backups import BRUSSELS, Archive, BackupStore, target_key

logger = logging.getLogger(__name__)
RETRY_DELAY = timedelta(minutes=5)
MAX_ATTEMPTS = 3
WORKER_STALE = timedelta(minutes=2)
# Dump and two archive inspections each have a 600 s timeout.
RUNNING_STALE = timedelta(minutes=35)


def latest_due(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware clock is required")
    local = now.astimezone(BRUSSELS)
    day = local.date() - timedelta(days=int(local.hour < 18))
    return datetime.combine(day, time(18), BRUSSELS).astimezone(UTC)


def next_due(now: datetime) -> datetime:
    day = latest_due(now).astimezone(BRUSSELS).date() + timedelta(days=1)
    return datetime.combine(day, time(18), BRUSSELS).astimezone(UTC)


class BackupSchedule:
    def __init__(self, store: BackupStore, url: str, *, healthy: Callable[[], bool]) -> None:
        self.store = store
        self.url = url
        self.healthy = healthy
        self.state_path = store.scope(url) / "schedule.json"
        self.lock_path = store.scope(url) / ".schedule.lock"

    def tick(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        try:
            with schedule_lock(self.lock_path) as acquired:
                if acquired:
                    self._tick(now)
        except Exception:
            # No exception text/traceback: driver and filesystem errors may contain secrets.
            logger.error("Backup scheduler state unavailable; inspect backup directory")

    def _save(self, state: ScheduleState) -> None:
        write_state(self.state_path, state)

    def _fail(self, state: ScheduleState, now: datetime, code: ErrorCode) -> None:
        state.running = False
        state.error_code = state.last_error_code = code
        state.last_failure_at = now
        state.failed_attempts += 1
        state.retry_at = (
            None if code in {"retention_failed", "archive_invalid"} else now + RETRY_DELAY
        )
        self._save(state)
        logger.error("Backup schedule failure: %s", code)

    def _reconcile(self, state: ScheduleState, now: datetime) -> None:
        if state.archive_name is None or (
            not state.running and state.completed_due_at == state.due_at
        ):
            return
        directory = self.store.scope(self.url) / "daily" / state.archive_name
        if directory.exists():
            archive = self.store._read(directory, target_key(self.url), "daily")
            self._success(state, archive)
        elif state.running:
            self._fail(state, now, "interrupted")

    def _success(self, state: ScheduleState, archive: Archive) -> None:
        state.running = False
        state.completed_due_at = state.due_at
        state.last_success_at = archive.created_at
        state.retry_at = None
        state.error_code = None
        self._save(state)
        logger.info("Backup verified for schedule %s", state.completed_due_at)

    def _tick(self, now: datetime) -> None:
        state = read_state(self.state_path)
        state.checked_at = now
        try:
            self._reconcile(state, now)
        except Exception:
            if state.error_code != "archive_invalid":
                self._fail(state, now, "archive_invalid")
            else:
                self._save(state)
            return
        due = latest_due(now)
        if state.completed_due_at is not None and state.completed_due_at >= due:
            self._save(state)
            return
        if state.due_at != due:
            state.due_at = due
            state.attempts = 0
            state.retry_at = None
            state.archive_name = None
        if not self.healthy():
            state.error_code = "dependencies_unhealthy"
            self._save(state)
            return
        if state.attempts >= MAX_ATTEMPTS or (state.retry_at and now < state.retry_at):
            self._save(state)
            return
        self._attempt(state, now)

    def _attempt(self, state: ScheduleState, now: datetime) -> None:
        state.attempts += 1
        state.started_at = now
        state.running = True
        state.error_code = None
        state.archive_name = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex
        self._save(state)  # Claim and exact publication path durable BEFORE any dump.
        try:
            archive = self.store.create(self.url, now=now, archive_name=state.archive_name)
        except Exception:
            code: ErrorCode = (
                "backup_locked"
                if (self.store.scope(self.url) / ".lock").exists()
                else "backup_failed"
            )
            self._fail(state, now, code)
            return
        self._success(state, archive)
        try:
            self.store.prune(self.url)
        except Exception:
            self._fail(state, now, "retention_failed")

    def status(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now(UTC)
        due = latest_due(now)
        try:
            state = read_state(self.state_path)
        except Exception:
            state = ScheduleState(error_code="state_unavailable")
        overdue = state.completed_due_at is None or state.completed_due_at < due
        code = state.error_code
        stale_after = RUNNING_STALE if state.running else WORKER_STALE
        if code is None and (state.checked_at is None or now - state.checked_at > stale_after):
            code = "worker_unavailable"
        label = "running" if state.running and code is None else "failed" if code else "ok"
        if overdue and label == "ok":
            label = "overdue"
        return {
            "state": label,
            "last_success_at": state.last_success_at,
            "last_failure_at": state.last_failure_at,
            "last_error_code": state.last_error_code,
            "error_code": code,
            "overdue": overdue,
            "attempts": state.attempts,
            "failed_attempts": state.failed_attempts,
            "next_due_at": next_due(now),
            "retry_at": state.retry_at if state.attempts < MAX_ATTEMPTS else None,
        }

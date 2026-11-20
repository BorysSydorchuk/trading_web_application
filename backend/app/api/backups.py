"""Read-only backup status. No dump, archive scans or DB writes in API requests."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.backup_schedule import BackupSchedule, next_due
from app.services.backup_state import ErrorCode
from app.services.backups import BackupStore
from app.system.db_mode import docker_compose_port

router = APIRouter()


class BackupStatus(BaseModel):
    state: Literal["ok", "running", "failed", "overdue"]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_code: ErrorCode | None
    error_code: ErrorCode | None
    overdue: bool
    attempts: int
    failed_attempts: int
    next_due_at: datetime
    retry_at: datetime | None


def get_backup_schedule(settings: Settings = Depends(get_settings)) -> BackupSchedule | None:
    try:
        return BackupSchedule(
            BackupStore(settings.backup_dir, compose_port=docker_compose_port(settings)),
            settings.database_url,
            healthy=lambda: False,
        )
    except Exception:
        return None


@router.get("/backups/status", response_model=BackupStatus)
def backup_status(schedule: BackupSchedule | None = Depends(get_backup_schedule)) -> BackupStatus:
    if schedule is None:
        return BackupStatus(
            state="failed",
            last_success_at=None,
            last_failure_at=None,
            last_error_code=None,
            error_code="state_unavailable",
            overdue=True,
            attempts=0,
            failed_attempts=0,
            next_due_at=next_due(datetime.now(UTC)),
            retry_at=None,
        )
    return BackupStatus.model_validate(schedule.status())

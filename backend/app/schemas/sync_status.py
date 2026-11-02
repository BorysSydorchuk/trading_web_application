"""GET /api/sync/status schema (docs/api.md M1 "Sync status")."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.common import UtcDatetime

SyncState = Literal["ok", "warning", "error", "running", "never", "stale"]


class AccountSyncStatus(BaseModel):
    account_id: int
    account_name: str
    state: SyncState
    last_attempt_utc: UtcDatetime | None
    last_success_utc: UtcDatetime | None
    error_code: str | None
    error_message: str | None
    server_offset_hours: int | None
    open_positions: int


class SyncStatusList(BaseModel):
    items: list[AccountSyncStatus]

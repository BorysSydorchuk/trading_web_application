"""Backup job uses a dedicated executor, never the MT5 lock or source."""

from __future__ import annotations

import json
import logging
from http.client import HTTPConnection

from app.config import Settings
from app.services.backup_schedule import BackupSchedule
from app.services.backups import BackupStore, target_key
from app.system.db_mode import docker_compose_port

BACKUP_JOB_ID = "daily_backup"
BACKUP_POLL_SECONDS = 15


def operational(settings: Settings) -> bool:
    """Local API health performs a fresh DB check; reject another app's DB target.

    No redirects, proxy, authentication or external requests. Optional AI/MT5 health
    is deliberately excluded: an unavailable terminal must not disable DB backups.
    """
    connection: HTTPConnection | None = None
    try:
        host = settings.api_host
        if host in {"0.0.0.0", "::"}:  # noqa: S104 - map bind wildcard to loopback
            host = "127.0.0.1"
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        connection = HTTPConnection(host, settings.api_port, timeout=5)
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        if response.status != 200:
            return False
        body = json.loads(response.read(65536))
        return (
            body.get("status") == "ok"
            and body.get("db", {}).get("ok") is True
            and body.get("backup_target") == target_key(settings.database_url)
        )
    except Exception:
        return False
    finally:
        if connection is not None:
            connection.close()


def make_backup_schedule(settings: Settings) -> BackupSchedule:
    return BackupSchedule(
        BackupStore(settings.backup_dir, compose_port=docker_compose_port(settings)),
        settings.database_url,
        healthy=lambda: operational(settings),
    )


class BackupJob:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def __call__(self) -> None:
        try:
            make_backup_schedule(self.settings).tick()
        except Exception:
            logging.getLogger(__name__).error("Backup configuration unavailable; check BACKUP_DIR")

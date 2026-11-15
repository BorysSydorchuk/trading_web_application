"""Backup HTTP status, no real DB, HTTP, MT5 or archive subprocesses."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.backups import get_backup_schedule
from app.api.health import DbHealth
from app.config import Settings, get_settings
from app.main import create_app
from app.services.backup_schedule import BackupSchedule
from app.services.backups import BackupStore


def test_status_reads_last_success_and_failure_without_exposing_paths(tmp_path: Path) -> None:
    def dump(url: str, path: Path) -> None:
        path.write_bytes(b"synthetic")

    job = BackupSchedule(
        BackupStore(tmp_path, dump=dump, verify=lambda p: None),
        "postgresql+psycopg://u:private@localhost/status_test",
        healthy=lambda: True,
    )
    job.tick(datetime.now(UTC))
    app = create_app()
    app.dependency_overrides[get_backup_schedule] = lambda: job
    response = TestClient(app, base_url="http://127.0.0.1").get("/api/backups/status")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ok"
    assert data["last_success_at"].endswith("Z")
    assert data["overdue"] is False
    assert "private" not in response.text
    assert str(tmp_path) not in response.text
    assert "archive_name" not in data


def test_status_corruption_returns_actionable_code(tmp_path: Path) -> None:
    job = BackupSchedule(
        BackupStore(tmp_path),
        "postgresql+psycopg://u:p@localhost/status_test",
        healthy=lambda: True,
    )
    job.state_path.parent.mkdir(parents=True)
    job.state_path.write_text("secret-not-json", encoding="utf-8")
    app = create_app()
    app.dependency_overrides[get_backup_schedule] = lambda: job
    response = TestClient(app, base_url="http://127.0.0.1").get("/api/backups/status")
    assert response.status_code == 200
    assert response.json()["error_code"] == "state_unavailable"
    assert "secret" not in response.text


def test_invalid_backup_directory_does_not_break_status(settings: Settings) -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={
            "backup_dir": Path(__file__).resolve().parents[2] / "config",
        }
    )
    response = TestClient(app, base_url="http://127.0.0.1").get("/api/backups/status")
    assert response.status_code == 200
    assert response.json()["error_code"] == "state_unavailable"


def test_unsupported_backup_target_does_not_break_health(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={
            "database_url": settings.database_url + "?application_name=synthetic",
        }
    )
    monkeypatch.setattr(
        "app.api.health.check_db", lambda db: DbHealth(ok=True, latency_ms=0, error=None)
    )
    response = TestClient(app, base_url="http://127.0.0.1").get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["backups"]["error_code"] == "state_unavailable"

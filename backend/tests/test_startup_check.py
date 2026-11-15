"""Startup preflight is read-only except unique disposable directory probes."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.tools import startup_check as startup


def settings_for(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, database_url="postgresql+psycopg://u:synthetic@localhost/startup_test",
                    data_dir=tmp_path / "data", log_dir=tmp_path / "logs", backup_dir=tmp_path / "backups")


def test_preflight_only_uses_local_readonly_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_for(tmp_path)
    check_db, tools = Mock(), Mock()
    monkeypatch.setattr(startup, "check_database", check_db)
    monkeypatch.setattr(startup, "check_backup_tools", tools)
    startup.check(settings)
    check_db.assert_called_once_with(settings)
    tools.assert_called_once_with(settings)
    assert not list(tmp_path.rglob("*.probe"))


def test_invalid_config_blocks_before_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup, "check_config_files", lambda: [object()])
    db = Mock()
    monkeypatch.setattr(startup, "check_database", db)
    with pytest.raises(startup.StartupFailure, match="конфігурац"):
        startup.check(settings_for(tmp_path))
    db.assert_not_called()


def test_unwritable_directory_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup.tempfile, "TemporaryFile", Mock(side_effect=PermissionError("credential")))
    with pytest.raises(startup.StartupFailure, match="запис") as error:
        startup.check_directories(settings_for(tmp_path))
    assert "credential" not in str(error.value)


def test_database_identity_mismatch_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=Mock(scalar=Mock(return_value="other_db")))
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(startup, "create_engine", Mock(return_value=engine))
    with pytest.raises(startup.StartupFailure, match="БД"):
        startup.check_database(settings_for(tmp_path))
    engine.dispose.assert_called_once()


def test_database_connection_failure_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup, "create_engine", Mock(side_effect=RuntimeError("secret")))
    with pytest.raises(startup.StartupFailure) as error:
        startup.check_database(settings_for(tmp_path))
    assert "secret" not in str(error.value)


def test_missing_backup_tools_fail_visibly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup.shutil, "which", lambda name: None)
    with pytest.raises(startup.StartupFailure, match="pg_dump"):
        startup.check_backup_tools(settings_for(tmp_path))

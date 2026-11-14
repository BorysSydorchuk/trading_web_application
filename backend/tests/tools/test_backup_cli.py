"""Manual backup command; scheduling belongs to M7-02."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Settings
from app.services.backups import Archive, BackupFailure
from app.tools import backup


def test_cli_never_exposes_external_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> Settings:
        raise BackupFailure("secret-must-not-leak")

    monkeypatch.setattr(backup, "get_settings", fail)
    assert backup.main([]) == 1
    captured = capsys.readouterr()
    assert "secret-must-not-leak" not in captured.err
    assert captured.err


def test_cli_manual_default_and_configurable_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    class Store:
        def __init__(self, root: Path, *, compose_port: int) -> None:
            calls.append((root, compose_port))

        def create(self, url: str, *, kind: str) -> Archive:
            calls.append(kind)
            return Archive(tmp_path, datetime(2026, 1, 1, tzinfo=UTC))

        def prune(self, url: str) -> list[Path]:
            calls.append("prune")
            return []

    monkeypatch.setattr(backup, "BackupStore", Store)
    monkeypatch.setattr(
        backup,
        "get_settings",
        lambda: Settings(
            _env_file=None, database_url="postgresql+psycopg://u:p@localhost/synthetic_test"
        ),
    )
    assert backup.main(["--root", str(tmp_path)]) == 0
    assert calls == [(tmp_path, 5432), "manual"]
    calls.clear()
    assert backup.main(["--root", str(tmp_path), "--kind", "daily"]) == 0
    assert calls == [(tmp_path, 5432), "daily", "prune"]

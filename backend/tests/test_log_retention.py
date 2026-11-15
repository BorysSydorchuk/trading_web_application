"""Synthetic application logs only; no real audit history is opened."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.logging_setup import UTCFormatter, setup_logging
from app.log_rotation import ProcessRotatingHandler


def handler(path: Path, size: int = 200, count: int = 2) -> ProcessRotatingHandler:
    result = ProcessRotatingHandler(path, maxBytes=size, backupCount=count, encoding="utf-8")
    result.setFormatter(UTCFormatter("%(message)s"))
    return result


def emit(target: logging.Handler, message: str) -> None:
    target.handle(logging.LogRecord("synthetic", logging.ERROR, __file__, 1, message, (), None))


def test_rollover_restart_utf8_and_retention_are_scoped(tmp_path: Path) -> None:
    audit = tmp_path / "ai_usage.jsonl"
    audit.write_bytes(b"audit-history\n")
    unrelated = tmp_path / "unrelated.log"
    unrelated.write_bytes(b"preserve")
    path = tmp_path / "api.log"
    for _ in range(2):
        with handler(path) as target:
            for number in range(40):
                emit(target, f"{number}: Синтетична помилка")
    assert path.exists() and path.with_name("api.log.2").exists()
    assert not path.with_name("api.log.3").exists()
    assert all(p.stat().st_size < 240 for p in tmp_path.glob("api.log*"))
    assert "Синтетична" in path.read_text(encoding="utf-8")
    assert audit.read_bytes() == b"audit-history\n"
    assert unrelated.read_bytes() == b"preserve"


@pytest.mark.parametrize("name", ["ai_usage.jsonl", "../worker.log", "audio/x.log", "api.log.1"])
def test_setup_rejects_audit_and_unsafe_names(tmp_path: Path, name: str) -> None:
    settings = Settings(_env_file=None, database_url="postgresql://u@localhost/synthetic_test", log_dir=tmp_path)
    with pytest.raises(ValueError, match="log"):
        setup_logging(name, settings)


def test_console_file_and_traceback_redact_secrets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(_env_file=None, database_url="postgresql://u:synthetic-db-secret@localhost/test",
                        log_dir=tmp_path, anthropic_api_key="synthetic-ai-secret")
    setup_logging("synthetic.log", settings)
    try:
        raise RuntimeError("synthetic-ai-secret password=unknown-secret")
    except RuntimeError:
        logging.getLogger("synthetic").exception("postgresql://u:synthetic-db-secret@localhost/test Authorization: Bearer bearer-secret")
    text = (tmp_path / "synthetic.log").read_text(encoding="utf-8") + capsys.readouterr().err
    for secret in ("synthetic-db-secret", "synthetic-ai-secret", "unknown-secret", "bearer-secret"):
        assert secret not in text
    assert "RuntimeError" in text and "[REDACTED]" in text

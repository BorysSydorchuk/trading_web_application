"""Synthetic application logs only; no real audit history is opened."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.log_rotation import ProcessRotatingHandler
from app.logging_setup import UTCFormatter, setup_logging


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
    assert path.exists()
    assert path.with_name("api.log.2").exists()
    assert not path.with_name("api.log.3").exists()
    assert all(p.stat().st_size < 240 for p in tmp_path.glob("api.log*"))
    assert "Синтетична" in path.read_text(encoding="utf-8")
    assert audit.read_bytes() == b"audit-history\n"
    assert unrelated.read_bytes() == b"preserve"


@pytest.mark.parametrize("name", ["ai_usage.jsonl", "../worker.log", "audio/x.log", "api.log.1"])
def test_setup_rejects_audit_and_unsafe_names(tmp_path: Path, name: str) -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql://u@localhost/synthetic_test", log_dir=tmp_path
    )
    with pytest.raises(ValueError, match="log"):
        setup_logging(name, settings)


def test_console_file_and_traceback_redact_secrets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:synthetic-db-secret@localhost/test",
        log_dir=tmp_path,
        anthropic_api_key=SecretStr("synthetic-ai-secret"),
    )
    setup_logging("synthetic.log", settings)
    try:
        raise RuntimeError("synthetic-ai-secret password=unknown-secret")
    except RuntimeError:
        logging.getLogger("synthetic").exception(
            "postgresql://u:synthetic-db-secret@localhost/test Authorization: Bearer bearer-secret"
        )
    text = (tmp_path / "synthetic.log").read_text(encoding="utf-8") + capsys.readouterr().err
    for secret in ("synthetic-db-secret", "synthetic-ai-secret", "unknown-secret", "bearer-secret"):
        assert secret not in text
    assert "RuntimeError" in text
    assert "[REDACTED]" in text


def test_concurrent_process_writers_and_restart_preserve_every_record(tmp_path: Path) -> None:
    script = """
import logging,sys
from app.log_rotation import ProcessRotatingHandler
h=ProcessRotatingHandler(sys.argv[1], maxBytes=350, backupCount=40)
h.setFormatter(logging.Formatter('%(message)s'))
for n in range(80):
    h.handle(logging.LogRecord('test',40,'',1,f'{sys.argv[2]}:{n}:помилка',(),None))
h.close()
"""
    path = tmp_path / "worker.log"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    processes = [
        subprocess.Popen(  # noqa: S603 - fixed synthetic script
            [sys.executable, "-c", script, str(path), str(number)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for number in range(3)
    ]
    for process in processes:
        _, errors = process.communicate(timeout=30)
        assert process.returncode == 0
        assert not errors
    lines = [
        line
        for p in tmp_path.glob("worker.log*")
        if p.suffix != ".lock"
        for line in p.read_text(encoding="utf-8").splitlines()
    ]
    assert set(lines) == {f"{p}:{n}:помилка" for p in range(3) for n in range(80)}
    assert len(lines) == 240


def test_threads_share_rotation_without_lost_records(tmp_path: Path) -> None:
    path = tmp_path / "api.log"
    with handler(path, 300, 20) as target:

        def write(number: int) -> None:
            for n in range(50):
                emit(target, f"{number}:{n}")

        threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
    lines = [
        line
        for p in tmp_path.glob("api.log*")
        if p.suffix != ".lock"
        for line in p.read_text(encoding="utf-8").splitlines()
    ]
    assert len(lines) == len(set(lines)) == 200


@pytest.mark.skipif(sys.platform != "win32", reason="actual Windows sharing violation")
def test_windows_foreign_file_lock_reports_safely_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import ctypes
    from ctypes import wintypes

    path = tmp_path / "worker.log"
    path.write_text("prior record\n", encoding="utf-8")
    create = ctypes.windll.kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle_value = create(str(path), 0x80000000, 0, None, 3, 0, None)
    assert handle_value != wintypes.HANDLE(-1).value
    try:
        with handler(path, 20) as target:
            emit(target, "secret-must-not-appear")
        error = capsys.readouterr().err
        assert "rotation failed" in error
        assert "secret-must-not-appear" not in error
    finally:
        ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle_value))
    with handler(path, 20) as target:
        emit(target, "recovered")
    assert "recovered" in path.read_text(encoding="utf-8")


def test_redaction_precedes_size_limit_and_traceback_cache() -> None:
    formatter = UTCFormatter("%(message)s", secrets=("synthetic-private-value",))
    record = logging.LogRecord(
        "test", 40, "", 1, "я" * 100000 + "synthetic-private-value", (), None
    )
    output = formatter.format(record)
    assert len(output.encode("utf-8")) < 66000
    assert output.endswith("[LOG TRUNCATED]")


def test_rotation_limit_counts_utf8_bytes(tmp_path: Path) -> None:
    path = tmp_path / "worker.log"
    with handler(path, 200, 5) as target:
        for _ in range(20):
            emit(target, "я" * 35)
    assert max(p.stat().st_size for p in tmp_path.glob("worker.log*") if p.suffix != ".lock") <= 200

"""M5-10 worker start: ``app.worker.main`` calls ``recompute_all`` (imported from
``app.services.risk_base``) once, after the symbol map and before the scheduler starts.
``recompute_all`` returns None on failure (it logs itself); the worker logs an ERROR mentioning
"risk base" and starts anyway.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings


def _patch_worker_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, settings: Settings, order: list[str]
) -> Any:
    from app.worker import main as worker_main

    class FakeScheduler:
        running = False

        def start(self) -> None:
            order.append("scheduler.start")
            raise KeyboardInterrupt

    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "setup_logging", lambda *_: tmp_path / "worker.log")
    monkeypatch.setattr(worker_main, "check_config_files", lambda: None)
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: "factory")
    monkeypatch.setattr(worker_main, "mark_interrupted_runs", lambda _f: None)
    monkeypatch.setattr(worker_main, "reset_interrupted_notes", lambda _f: None)
    monkeypatch.setattr(worker_main, "mark_interrupted_margin_requests", lambda _f: 0)
    monkeypatch.setattr(worker_main, "reapply_symbol_map", lambda _f, **_kw: 0)
    monkeypatch.setattr(worker_main, "_install_signal_handlers", lambda _stop: None)
    monkeypatch.setattr(worker_main, "build_scheduler", lambda *_a, **_k: FakeScheduler())
    monkeypatch.setattr(worker_main, "dispose_engine", lambda: None)
    return worker_main


def test_worker_start_recomputes_the_risk_base_before_jobs_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    order: list[str] = []
    worker_main = _patch_worker_start(monkeypatch, tmp_path, settings, order)

    def fake_recompute(session_factory: Any) -> int:
        assert session_factory == "factory"
        order.append("risk_base")
        return 3

    monkeypatch.setattr(worker_main, "recompute_all", fake_recompute)

    assert worker_main.main() == 0

    assert order == ["risk_base", "scheduler.start"]


def test_worker_starts_even_when_the_risk_base_recompute_fails(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    order: list[str] = []
    worker_main = _patch_worker_start(monkeypatch, tmp_path, settings, order)
    monkeypatch.setattr(worker_main, "recompute_all", lambda _f: None)

    with caplog.at_level(logging.ERROR, logger="app.worker.main"):
        assert worker_main.main() == 0

    assert order == ["scheduler.start"]
    assert any(
        r.levelno == logging.ERROR and "risk base" in r.getMessage().lower() for r in caplog.records
    )

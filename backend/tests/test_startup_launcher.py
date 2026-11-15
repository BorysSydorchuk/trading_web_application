"""Launcher gaps, injected processes and clocks; existing ownership tests also apply."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_dev_script import dev


@pytest.mark.parametrize("version", [(3, 11, 9), (3, 13, 0), (3, 14, 0)])
def test_unsupported_python_rejected(version: tuple[int, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev.sys, "version_info", version)
    with pytest.raises(dev.LauncherError, match="3.12"):
        dev.check_python()


@pytest.mark.parametrize("version", ["v20.18.0", "v21.7.0", "v22.11.0"])
def test_vite_engine_node_ranges(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev.shutil, "which", lambda name: name)
    monkeypatch.setattr(dev.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=version, returncode=0))
    with pytest.raises(dev.LauncherError, match="Node"):
        dev.find_npm()


def test_ready_requires_worker_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "READY_TIMEOUT_S", 0.1)
    run = Mock(worker_ready=Mock(return_value=False))
    monkeypatch.setattr(dev, "http_get", lambda *a: (200, b'{"status":"ok","db":{"ok":true}}'))
    with pytest.raises(dev.LauncherError, match="воркер"):
        dev.wait_ready(run)


def test_degraded_database_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "READY_TIMEOUT_S", 0.1)
    run = Mock(worker_ready=Mock(return_value=True))
    monkeypatch.setattr(dev, "http_get", lambda *a: (200, b'{"status":"degraded","db":{"ok":false}}'))
    with pytest.raises(dev.LauncherError, match="API"):
        dev.wait_ready(run)


def test_exited_child_is_not_killed_by_reused_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    child = SimpleNamespace(proc=Mock(pid=123, poll=Mock(return_value=1)))
    kill = Mock()
    monkeypatch.setattr(dev.subprocess, "run", kill)
    dev.kill_tree(child)
    kill.assert_not_called()

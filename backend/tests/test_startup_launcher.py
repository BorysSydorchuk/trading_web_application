"""Launcher gaps, injected processes and clocks; existing ownership tests also apply."""

from __future__ import annotations

import io
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_dev_script import dev


@pytest.mark.parametrize("version", [(3, 11, 9), (3, 13, 0), (3, 14, 0)])
def test_unsupported_python_rejected(
    version: tuple[int, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dev.sys, "version_info", version)
    with pytest.raises(dev.LauncherError, match=r"3\.12"):
        dev.check_python()


@pytest.mark.parametrize("version", ["v20.18.0", "v21.7.0", "v22.11.0"])
def test_vite_engine_node_ranges(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        dev.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=version, returncode=0)
    )
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
    monkeypatch.setattr(
        dev, "http_get", lambda *a: (200, b'{"status":"degraded","db":{"ok":false}}')
    )
    with pytest.raises(dev.LauncherError, match="API"):
        dev.wait_ready(run)


def test_exited_child_is_not_killed_by_reused_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    child = SimpleNamespace(proc=Mock(pid=123, poll=Mock(return_value=1)))
    kill = Mock()
    monkeypatch.setattr(dev.subprocess, "run", kill)
    dev.kill_tree(child)
    kill.assert_not_called()


@pytest.mark.parametrize("dependency", ["uv", "node", "npm"])
def test_missing_dependencies(dependency: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev.shutil, "which", lambda name: None if name == dependency else name)
    monkeypatch.setattr(dev.subprocess, "run", Mock(side_effect=OSError("secret")))
    with pytest.raises(dev.LauncherError) as error:
        (dev.find_uv if dependency == "uv" else dev.find_npm)()
    assert "secret" not in str(error.value)


def test_npm_cannot_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev.shutil, "which", lambda name: name)

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[0] == "npm":
            raise subprocess.TimeoutExpired(command, 20)
        return SimpleNamespace(stdout="v24.0.0", returncode=0)

    monkeypatch.setattr(dev.subprocess, "run", run)
    with pytest.raises(dev.LauncherError, match="npm"):
        dev.find_npm()


def test_readiness_timeout_never_hides_child_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock()
    run.check.side_effect = dev.LauncherError("worker несподівано завершився")
    with pytest.raises(dev.LauncherError, match="завершився"):
        dev.wait_ready(run)


def test_preflight_failure_cleans_only_started_children(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ensure_ports_free", "ensure_env_file", "ensure_dependencies", "ensure_db"):
        monkeypatch.setattr(dev, name, Mock())
    monkeypatch.setattr(dev, "find_uv", lambda: ["uv"])
    monkeypatch.setattr(dev, "find_npm", lambda: "npm")
    monkeypatch.setattr(dev, "load_env", lambda: {})
    instance = Mock()
    monkeypatch.setattr(dev, "Run", Mock(return_value=instance))
    web = object()
    start = Mock(return_value=web)
    monkeypatch.setattr(dev, "start_child", start)
    monkeypatch.setattr(dev, "run_step", Mock(side_effect=dev.LauncherError("preflight")))
    migrate = Mock()
    monkeypatch.setattr(dev, "migrate", migrate)
    with pytest.raises(dev.LauncherError, match="preflight"):
        dev.run_dev(False, 0)
    assert start.call_count == 1
    instance.add.assert_called_once_with(web)
    instance.close.assert_called_once()
    migrate.assert_not_called()


def test_worker_ack_survives_interleaved_scheduler_output() -> None:
    line = "TJ_WORKER_READY:" + dev.STARTUP_TOKEN + "2026 scheduler heartbeat\n"
    child = dev.Child("worker", SimpleNamespace(pid=os.getpid(), stdout=io.BytesIO(line.encode())))
    child.reader.join(2)
    assert child.ready.is_set()


def test_health_must_still_be_ready_when_worker_ack_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "READY_TIMEOUT_S", 0.4)
    healthy = b'{"status":"ok","db":{"ok":true}}'
    degraded = b'{"status":"degraded","db":{"ok":false}}'
    calls = 0

    def http(url: str) -> tuple[int, bytes]:
        nonlocal calls
        if url == dev.HEALTH_URL:
            calls += 1
            return 200, healthy if calls == 1 else degraded
        return 200, b"web"

    run = Mock()
    run.worker_ready.side_effect = [False, True, True, True]
    monkeypatch.setattr(dev, "http_get", http)
    with pytest.raises(dev.LauncherError, match="API"):
        dev.wait_ready(run)

"""Unit tests for the pure helpers of the dev launcher `scripts/dev.py` (no processes started)."""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tj_dev_launcher", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


dev = _load()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+psycopg://journal:journal@127.0.0.1:5432/tj", ("127.0.0.1", 5432)),
        ("postgresql+psycopg://u:p@localhost:5433/db", ("localhost", 5433)),
        ("postgresql://u:p@db.example.com/db", ("db.example.com", 5432)),
        ("postgresql+psycopg://u@/db", ("localhost", 5432)),
        ("postgresql+psycopg://u:p%40ss%3Aw@127.0.0.1:6543/db", ("127.0.0.1", 6543)),
        ("postgresql+psycopg://u:p@[::1]:5432/db", ("::1", 5432)),
        ("postgres://u:p@HostName:5432/db", ("hostname", 5432)),
    ],
)
def test_parse_db_host_port(url: str, expected: tuple[str, int]) -> None:
    assert dev.parse_db_host_port(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "127.0.0.1:5432",
        "mysql://u:p@127.0.0.1:3306/db",
        "postgresql://u:p@127.0.0.1:notaport/db",
        "postgresql://u:p@127.0.0.1:99999/db",
    ],
)
def test_parse_db_host_port_rejects_bad_urls(url: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - any readable ValueError is fine
        dev.parse_db_host_port(url)


def test_parse_env_file() -> None:
    text = (
        "# comment\n"
        "\n"
        "DATABASE_URL=postgresql+psycopg://a:b@h:1/d\n"
        'QUOTED="with spaces"\n'
        "SINGLE='x=y'\n"
        "export EXPORTED=1\n"
        "EMPTY=\n"
        "not a pair\n"
        "  SPACED = v  \n"
    )
    assert dev.parse_env_file(text) == {
        "DATABASE_URL": "postgresql+psycopg://a:b@h:1/d",
        "QUOTED": "with spaces",
        "SINGLE": "x=y",
        "EXPORTED": "1",
        "EMPTY": "",
        "SPACED": "v",
    }


def _touch(path: Path, mtime: float) -> Path:
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_needs_install_when_stamp_missing(tmp_path: Path) -> None:
    lock = _touch(tmp_path / "uv.lock", 1_000)
    assert dev.needs_install(tmp_path / "stamp", [lock]) is True


def test_needs_install_when_manifest_newer(tmp_path: Path) -> None:
    stamp = _touch(tmp_path / "stamp", 1_000)
    lock = _touch(tmp_path / "uv.lock", 2_000)
    assert dev.needs_install(stamp, [lock]) is True


def test_no_install_when_stamp_newer(tmp_path: Path) -> None:
    lock = _touch(tmp_path / "uv.lock", 1_000)
    pyproject = _touch(tmp_path / "pyproject.toml", 1_500)
    stamp = _touch(tmp_path / "stamp", 2_000)
    assert dev.needs_install(stamp, [lock, pyproject, tmp_path / "missing.json"]) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [("v22.12.0\n", (22, 12)), ("v20.19.1", (20, 19)), ("24", (24, 0))],
)
def test_parse_node_version(text: str, expected: tuple[int, int]) -> None:
    assert dev.parse_node_version(text) == expected


def test_is_local_host() -> None:
    assert dev.is_local_host("127.0.0.1")
    assert dev.is_local_host("LOCALHOST")
    assert dev.is_local_host("::1")
    assert not dev.is_local_host("db.example.com")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://journal:Xq9/Zw7@127.0.0.1:5432/db",
        "postgresql+psycopg://journal:Xq9#Zw7@127.0.0.1:5432/db",
        "postgresql+psycopg://journal:Xq9?Zw7@127.0.0.1:5432/db",
        "postgresql+psycopg://journal:77/Zw7@127.0.0.1:5432/db",
    ],
)
def test_unencoded_password_never_leaks(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError) as parse_err:  # noqa: PT011
        dev.parse_db_host_port(url)
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: True)
    with pytest.raises(dev.LauncherError) as launch_err:
        dev.ensure_db({"DATABASE_URL": url})
    for message in (str(parse_err.value), str(launch_err.value)):
        assert "URL-encode" in message
        for fragment in ("Xq9", "Zw7", "77"):
            assert fragment not in message


def test_port_in_use() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        assert dev.port_in_use(port) is True
    assert dev.port_in_use(port) is False


LOCAL_URL = "postgresql+psycopg://u:p@127.0.0.1:5432/db"


@pytest.fixture
def db_down(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """DB unreachable; no real docker/network calls."""
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: False)
    monkeypatch.setattr(dev, "docker_daemon_running", lambda _d: False)
    monkeypatch.setattr(dev, "try_start_docker_desktop", lambda _d: False)

    def no_steps(*_a: object, **_k: object) -> None:
        raise AssertionError("no setup command expected")

    monkeypatch.setattr(dev, "run_step", no_steps)
    return monkeypatch


def test_ensure_db_reachable_does_nothing_else(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev, "tcp_reachable", lambda *_a, **_k: True)
    dev.ensure_db({"DATABASE_URL": LOCAL_URL})


def test_ensure_db_remote_host(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev.shutil, "which", lambda _n: "docker")
    with pytest.raises(dev.LauncherError, match="remote host"):
        dev.ensure_db({"DATABASE_URL": "postgresql+psycopg://u:p@db.example.com:5432/db"})


def test_ensure_db_no_docker(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev.shutil, "which", lambda _n: None)
    with pytest.raises(dev.LauncherError, match="Install Docker Desktop"):
        dev.ensure_db({"DATABASE_URL": LOCAL_URL})


def test_ensure_db_daemon_down(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev.shutil, "which", lambda _n: "docker")
    with pytest.raises(dev.LauncherError, match="daemon is not running"):
        dev.ensure_db({"DATABASE_URL": LOCAL_URL})


def test_ensure_db_starts_compose_when_daemon_up(db_down: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    reachable = iter([False, True])
    db_down.setattr(dev.shutil, "which", lambda _n: "docker")
    db_down.setattr(dev, "docker_daemon_running", lambda _d: True)
    db_down.setattr(dev, "tcp_reachable", lambda *_a, **_k: next(reachable))
    db_down.setattr(dev, "run_step", lambda cmd, *_a, **_k: calls.append(list(cmd)))
    dev.ensure_db({"DATABASE_URL": LOCAL_URL})
    assert calls == [["docker", "compose", "up", "-d", "--wait", "db"]]


def test_ensure_db_empty_url(db_down: pytest.MonkeyPatch) -> None:
    with pytest.raises(dev.LauncherError, match="DATABASE_URL is not set"):
        dev.ensure_db({"DATABASE_URL": ""})


class _FakeProc:
    def __init__(self, code: int | None) -> None:
        self.pid = 4242
        self._code = code

    def poll(self) -> int | None:
        return self._code


def test_check_children() -> None:
    alive = SimpleNamespace(name="web", proc=_FakeProc(None))
    dev.check_children([alive])
    dead = SimpleNamespace(name="api", proc=_FakeProc(3))
    with pytest.raises(dev.LauncherError, match=r"api exited unexpectedly \(exit code 3\)"):
        dev.check_children([alive, dead])

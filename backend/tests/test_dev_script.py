"""Unit tests for the dev launcher `scripts/dev.py` (no processes started or killed)."""

# Messages under test are Ukrainian (Cyrillic look-alike letters are intended).
# ruff: noqa: RUF001

from __future__ import annotations

import importlib.util
import json
import os
import socket
import struct
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

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


# --------------------------------------------------------------------------- database / Docker

LOCAL_URL = "postgresql+psycopg://u:p@127.0.0.1:5432/db"


@pytest.fixture
def db_down(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """DB unreachable; no real docker/network calls, no Docker Desktop installed."""
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: False)
    monkeypatch.setattr(dev, "docker_daemon_running", lambda _d: False)
    monkeypatch.setattr(dev, "docker_desktop_exe", lambda: None)
    monkeypatch.setattr(dev.time, "sleep", lambda _s: None)

    def forbidden(*_a: object, **_k: object) -> bool:
        raise AssertionError("no setup command expected")

    monkeypatch.setattr(dev, "run_step", forbidden)
    monkeypatch.setattr(dev, "launch_docker_desktop", forbidden)
    return monkeypatch


def test_ensure_db_reachable_does_nothing_else(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev, "tcp_reachable", lambda *_a, **_k: True)
    dev.ensure_db({"DATABASE_URL": LOCAL_URL})


def test_ensure_db_remote_host(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev.shutil, "which", lambda _n: None)
    with pytest.raises(dev.LauncherError, match="віддалений сервер"):
        dev.ensure_db({"DATABASE_URL": "postgresql+psycopg://u:p@db.example.com:5432/db"})


def test_ensure_db_no_docker(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev.shutil, "which", lambda _n: None)
    with pytest.raises(dev.LauncherError, match="Встановіть Docker Desktop"):
        dev.ensure_db({"DATABASE_URL": LOCAL_URL})


def test_ensure_db_daemon_down_no_desktop(db_down: pytest.MonkeyPatch) -> None:
    db_down.setattr(dev.shutil, "which", lambda _n: "docker")
    with pytest.raises(dev.LauncherError, match="запустити його автоматично не вдалося"):
        dev.ensure_db({"DATABASE_URL": LOCAL_URL})


def test_docker_desktop_started_and_waited(
    db_down: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    launched: list[Path] = []
    daemon = iter([False, False, True])

    def launch(exe: Path) -> bool:
        launched.append(exe)
        return True

    db_down.setattr(dev, "docker_desktop_exe", lambda: tmp_path / "Docker Desktop.exe")
    db_down.setattr(dev, "launch_docker_desktop", launch)
    db_down.setattr(dev, "docker_daemon_running", lambda _d: next(daemon))
    dev.ensure_docker_daemon("docker", "127.0.0.1", 5432)
    assert launched == [tmp_path / "Docker Desktop.exe"]
    out = capsys.readouterr().out
    assert "Docker Desktop не запущено — запускаю, чекаю до 60 с…" in out
    assert dev.DOCKER_START_TIMEOUT_S == 60.0


def test_docker_desktop_timeout(db_down: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_down.setattr(dev, "docker_desktop_exe", lambda: tmp_path / "Docker Desktop.exe")
    db_down.setattr(dev, "launch_docker_desktop", lambda _exe: True)
    db_down.setattr(dev, "DOCKER_START_TIMEOUT_S", 0.01)
    with pytest.raises(dev.LauncherError, match="Docker Desktop не запустився"):
        dev.ensure_docker_daemon("docker", "127.0.0.1", 5432)


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
    with pytest.raises(dev.LauncherError, match="DATABASE_URL не задано"):
        dev.ensure_db({"DATABASE_URL": ""})


# --------------------------------------------------------------------------- children


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
    with pytest.raises(dev.LauncherError, match=r"api несподівано завершився \(код виходу 3\)"):
        dev.check_children([alive, dead])


# --------------------------------------------------------------------------- run file


def _rec(role: str, pid: int, ctime: int = 1000, cmd: str | None = None) -> Any:
    return dev.RunRecord(role, pid, ctime, cmd if cmd is not None else f"{role}.exe run")


def _info(pid: int, ctime: int | None = 1000, cmd: str | None = None, name: str = "x.exe") -> Any:
    return dev.ProcInfo(pid, name, ctime, cmd)


def test_run_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "dev-run.json"
    records = [_rec("launcher", 10), _rec("web", 11, 2000), _rec("api", 12, 3000, "uv run")]
    dev.write_run_file(path, records)
    assert dev.read_run_file(path) == records
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ports"] == [8000, 5173]
    assert data["root"] == str(dev.ROOT)
    assert data["started_at"].endswith("+00:00")


@pytest.mark.parametrize(
    "content",
    [
        None,  # missing
        "not json",
        "[]",
        json.dumps({"version": 1, "root": "C:\\other\\checkout", "processes": []}),
        json.dumps({"version": 99, "root": str(dev.ROOT), "processes": []}),
        json.dumps({"version": 1, "root": str(dev.ROOT), "processes": [{"pid": 1}]}),
    ],
)
def test_read_run_file_ignores_bad_files(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "dev-run.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert dev.read_run_file(path) == []


def test_recorded_process_ownership() -> None:
    rec = _rec("api", 500, 1000, "uv run uvicorn")
    assert dev.is_recorded_process(rec, _info(500, 1000, "uv run uvicorn"))
    # PID reused by another process: different creation time and/or command line.
    assert not dev.is_recorded_process(rec, _info(500, 2000, "uv run uvicorn"))
    assert not dev.is_recorded_process(rec, _info(500, 1000, "notepad.exe"))
    assert not dev.is_recorded_process(rec, _info(500, None, None))
    assert not dev.is_recorded_process(rec, None)


def test_is_app_process() -> None:
    root = dev.ROOT
    assert dev.is_app_process(_info(1, cmd=f'"{root / "backend" / ".venv" / "python.exe"}" -m x'))
    assert dev.is_app_process(_info(1, cmd=f"node {root / 'frontend' / 'node_modules' / 'v.js'}"))
    assert not dev.is_app_process(_info(1, cmd=f"{root.parent / 'other' / 'backend' / 'x'}"))
    assert not dev.is_app_process(_info(1, cmd=f"{root / 'backend-old' / 'x'}"))
    assert not dev.is_app_process(_info(1, cmd="python -m http.server 8000"))
    assert not dev.is_app_process(_info(1, cmd=None))


def _tcp4_row(port: int, pid: int) -> bytes:
    head = struct.pack("<II", 2, 0) + port.to_bytes(2, "big") + b"\0\0"
    return head + struct.pack("<III", 0, 0, pid)


def test_parse_tcp_owner_table() -> None:
    raw = struct.pack("<I", 3) + _tcp4_row(8000, 11) + _tcp4_row(5173, 22) + _tcp4_row(8000, 33)
    assert dev.parse_tcp_owner_table(raw, dev.TCP4_ROW, 8000) == {11, 33}
    assert dev.parse_tcp_owner_table(raw, dev.TCP4_ROW, 5173) == {22}
    assert dev.parse_tcp_owner_table(raw, dev.TCP4_ROW, 9999) == set()
    assert dev.parse_tcp_owner_table(raw[:30], dev.TCP4_ROW, 5173) == set()  # truncated
    assert dev.parse_tcp_owner_table(b"", dev.TCP4_ROW, 8000) == set()
    row6 = bytes(20) + (8000).to_bytes(2, "big") + bytes(30) + struct.pack("<I", 44)
    assert dev.parse_tcp_owner_table(struct.pack("<I", 1) + row6, dev.TCP6_ROW, 8000) == {44}


# --------------------------------------------------------------------------- previous run


class FakeSystem:
    """Process table, listeners and taskkill, patched into the launcher."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.procs: dict[int, Any] = {}
        self.children: dict[int, list[int]] = {}
        self.listeners: dict[int, set[int]] = {}
        self.killed: list[int] = []
        self.immortal: set[int] = set()  # taskkill refused (e.g. access denied)
        monkeypatch.setattr(dev, "RUN_FILE", tmp_path / "dev-run.json")
        monkeypatch.setattr(dev, "STOP_REQUEST_FILE", tmp_path / "dev-stop-request.json")
        monkeypatch.setattr(dev, "GRACEFUL_STOP_S", 0.0)
        monkeypatch.setattr(dev, "PROCESS_EXIT_TIMEOUT_S", 0.0)
        monkeypatch.setattr(dev, "PORT_FREE_TIMEOUT_S", 0.0)
        monkeypatch.setattr(dev.time, "sleep", lambda _s: None)
        monkeypatch.setattr(dev, "query_process", self.procs.get)
        monkeypatch.setattr(dev, "listening_pids", lambda port: set(self.listeners.get(port, ())))
        monkeypatch.setattr(
            dev, "process_names", lambda: {p: i.name for p, i in self.procs.items()}
        )
        monkeypatch.setattr(dev, "kill_process_tree", self.kill)
        monkeypatch.setattr(dev, "port_in_use", lambda port, *_a: bool(self.listeners.get(port)))

    def add(self, info: Any, parent: int | None = None, port: int | None = None) -> Any:
        self.procs[info.pid] = info
        if parent is not None:
            self.children.setdefault(parent, []).append(info.pid)
        if port is not None:
            self.listeners.setdefault(port, set()).add(info.pid)
        return info

    def kill(self, pid: int) -> str | None:
        self.killed.append(pid)
        if pid in self.immortal:
            return "ERROR: Access is denied."
        for child in self.children.get(pid, []):
            self.kill(child)
        self.procs.pop(pid, None)
        for pids in self.listeners.values():
            pids.discard(pid)
        return None


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSystem:
    return FakeSystem(monkeypatch, tmp_path)


APP_PY = str(dev.ROOT / "backend" / ".venv" / "Scripts" / "python.exe") + " -m uvicorn"
APP_NODE = "node " + str(dev.ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js")
LAUNCHER_CMD = "python scripts\\dev.py"


def test_stop_previous_run_kills_verified_tree_only(fake: FakeSystem) -> None:
    fake.add(_info(100, 1, LAUNCHER_CMD, "python.exe"))
    web = fake.add(_info(101, 2, "cmd /c npm run dev", "cmd.exe"), parent=100)
    fake.add(_info(102, 3, APP_NODE, "node.exe"), parent=101, port=5173)
    fake.add(_info(103, 999, "notepad.exe", "notepad.exe"))  # recorded api PID, reused
    dev.write_run_file(
        dev.RUN_FILE,
        [
            _rec("launcher", 100, 1, LAUNCHER_CMD),
            _rec("web", 101, 2, web.cmdline),
            _rec("api", 103, 4, "uv run uvicorn"),
        ],
    )
    result = dev.stop_previous_run()
    assert fake.killed[0] == 100  # launcher tree first (graceful stop timed out)
    assert set(fake.killed) == {100, 101, 102}
    assert 103 in fake.procs  # the reused PID is never touched
    assert len(result.stopped) == 2
    assert result.failed == []
    assert not dev.RUN_FILE.exists()
    assert not dev.STOP_REQUEST_FILE.exists()


def test_stop_request_targets_one_launcher(fake: FakeSystem) -> None:
    own = _rec("launcher", 100, 1)
    assert not dev.stop_requested(own)
    dev.STOP_REQUEST_FILE.write_text(json.dumps({"pid": 100, "create_time": 1}), encoding="utf-8")
    assert dev.stop_requested(own)
    assert not dev.stop_requested(_rec("launcher", 100, 2))  # same PID, other process
    assert not dev.stop_requested(None)


def test_graceful_stop_does_not_force_kill(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.add(_info(100, 1, LAUNCHER_CMD))
    dev.write_run_file(dev.RUN_FILE, [_rec("launcher", 100, 1, LAUNCHER_CMD)])

    request_seen: list[bool] = []

    def launcher_obeys(_records: object, _timeout: float) -> bool:
        request_seen.append(dev.STOP_REQUEST_FILE.exists())
        fake.procs.pop(100, None)
        return True

    monkeypatch.setattr(dev, "wait_records_gone", launcher_obeys)
    result = dev.stop_previous_run()
    assert request_seen[0] is True
    assert fake.killed == []
    assert len(result.stopped) == 1
    assert not dev.STOP_REQUEST_FILE.exists()


def test_orphan_port_holder_of_this_app_is_stopped(fake: FakeSystem) -> None:
    fake.add(_info(200, 5, APP_PY, "python.exe"), port=8000)  # parent gone, no run file
    dev.ensure_ports_free()
    assert fake.killed == [200]


def test_foreign_port_holder_is_reported_not_killed(fake: FakeSystem) -> None:
    fake.add(_info(300, 5, "python -m http.server 8000 --bind 127.0.0.1", "python.exe"), port=8000)
    with pytest.raises(dev.LauncherError) as err:
        dev.ensure_ports_free()
    assert fake.killed == []
    assert 300 in fake.procs
    message = str(err.value)
    assert "Порт 8000 зайнятий іншою програмою: python.exe (PID 300)" in message
    assert "taskkill /PID 300 /F" in message


def test_port_holder_without_access_is_foreign(fake: FakeSystem) -> None:
    fake.add(_info(4, None, None, "System"), port=5173)
    with pytest.raises(dev.LauncherError, match=r"System \(PID 4\)"):
        dev.ensure_ports_free()
    assert fake.killed == []


def test_busy_port_with_unknown_holder(fake: FakeSystem, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "port_in_use", lambda port, *_a: port == 8000)
    with pytest.raises(dev.LauncherError, match="netstat -ano"):
        dev.ensure_ports_free()


def test_ports_free_and_no_run_file(fake: FakeSystem) -> None:
    dev.ensure_ports_free()
    assert fake.killed == []


def test_stop_when_nothing_runs(fake: FakeSystem, capsys: pytest.CaptureFixture[str]) -> None:
    assert dev.main(["--stop"]) == 0
    assert dev.MSG["stop_nothing"] in capsys.readouterr().out
    assert fake.killed == []


def test_stop_stops_previous_run_and_keeps_foreign(
    fake: FakeSystem, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add(_info(100, 1, LAUNCHER_CMD, "python.exe"))
    fake.add(_info(101, 2, APP_NODE, "node.exe"), parent=100, port=5173)
    fake.add(_info(300, 5, "python -m http.server 8000", "python.exe"), port=8000)
    dev.write_run_file(dev.RUN_FILE, [_rec("launcher", 100, 1, LAUNCHER_CMD)])
    assert dev.main(["--stop"]) == 0
    out = capsys.readouterr().out
    assert dev.MSG["stop_done"] in out
    assert "python.exe (PID 300)" in out
    assert fake.killed == [100, 101]
    assert 300 in fake.procs


WORKER_CMD = f'"{dev.ROOT / "backend" / ".venv" / "Scripts" / "python.exe"}" -m app.worker'


def test_is_worker_process() -> None:
    assert dev.is_worker_process(_info(1, cmd=WORKER_CMD))
    assert not dev.is_worker_process(_info(1, cmd="python.exe -m app.worker"))  # no checkout path
    other = dev.ROOT.parent / "other" / "backend" / ".venv" / "Scripts" / "python.exe"
    assert not dev.is_worker_process(_info(1, cmd=f'"{other}" -m app.worker'))
    pytest_cmd = f'"{dev.ROOT / "backend" / ".venv" / "Scripts" / "python.exe"}" -m pytest'
    assert not dev.is_worker_process(_info(1, cmd=pytest_cmd))
    assert not dev.is_worker_process(_info(1, cmd=None))


def test_orphan_worker_without_run_file_is_stopped(fake: FakeSystem) -> None:
    fake.add(_info(400, 5, WORKER_CMD, "python.exe"))
    fake.add(_info(401, 6, "python.exe -m app.worker", "python.exe"), parent=400)
    fake.add(_info(402, 7, WORKER_CMD.replace("app.worker", "pytest"), "python.exe"))
    result = dev.stop_previous_run()
    assert fake.killed == [400, 401]
    assert 402 in fake.procs
    assert len(result.stopped) == 1


def test_surviving_process_is_reported_and_blocks_start(
    fake: FakeSystem, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add(_info(400, 5, WORKER_CMD, "python.exe"))
    fake.immortal.add(400)
    with pytest.raises(dev.LauncherError, match="Не вдалося зупинити процеси попереднього"):
        dev.ensure_ports_free()
    out = capsys.readouterr().out
    assert "ERROR: Access is denied." in out
    assert "Зупинено:" not in out
    assert 400 in fake.procs


def test_stop_reports_survivor_and_fails(
    fake: FakeSystem, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add(_info(100, 1, LAUNCHER_CMD, "python.exe"))
    fake.immortal.add(100)
    dev.write_run_file(dev.RUN_FILE, [_rec("launcher", 100, 1, LAUNCHER_CMD)])
    assert dev.main(["--stop"]) == 1
    out = capsys.readouterr().out
    assert "Зупинено не все" in out
    assert dev.MSG["stop_done"] not in out


def test_kill_reported_ok_but_process_survives(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add(_info(200, 5, APP_PY, "python.exe"), port=8000)
    monkeypatch.setattr(dev, "kill_process_tree", lambda _pid: None)  # "success", still alive
    result = dev.stop_previous_run()
    assert result.stopped == []
    assert result.failed == ["python.exe (PID 200)"]
    assert dev.MSG["proc_still_running"] in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "win32", reason="Docker Desktop autostart is Windows-only")
def test_docker_desktop_started_outside_our_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    kwargs: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **k: object) -> SimpleNamespace:
        calls.append(cmd)
        kwargs.append(k)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dev.subprocess, "run", fake_run)
    exe = tmp_path / "Docker Desktop.exe"
    assert dev.launch_docker_desktop(exe) is True
    assert calls == [["cmd", "/c", "start", "", str(exe)]]
    # Pipes would be inherited by Docker Desktop and make run() wait until it exits.
    assert "capture_output" not in kwargs[0]
    assert dev.subprocess.PIPE not in kwargs[0].values()

"""DB mode (native | docker): one resolution table for the backend and scripts/dev.py, and the
guarantee that native mode never invokes `docker` (launcher, backups, migrate, preflight)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import backups as b
from app.system import db_mode as dbm
from app.tools import migrate as mig
from app.tools import startup_check as startup
from app.tools import taxonomy_dry_run as dry

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev.py"


def _load_dev() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tj_dev_launcher_db_mode", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dev = _load_dev()

# (DB_MODE, host, port, NATIVE_PG_PORT, POSTGRES_PORT) -> mode; shared by both implementations.
CASES: list[tuple[str | None, str, int, int, int, str]] = [
    (None, "127.0.0.1", 5433, 5433, 5432, "native"),
    (None, "127.0.0.1", 5432, 5433, 5432, "docker"),
    (None, "localhost", 5432, 5433, 5432, "docker"),
    (None, "LOCALHOST", 5432, 5433, 5432, "docker"),
    (None, "::1", 5432, 5433, 5432, "docker"),
    (None, "db.example.com", 5432, 5433, 5432, "native"),
    (None, "db.example.com", 5433, 5433, 5432, "native"),
    (None, "127.0.0.1", 6000, 5433, 5432, "native"),
    (None, "127.0.0.1", 5440, 5433, 5440, "docker"),
    (None, "127.0.0.1", 6000, 6000, 5432, "native"),
    (None, "127.0.0.1", 5433, 5433, 5433, "native"),
    ("", "127.0.0.1", 5432, 5433, 5432, "docker"),
    ("  ", "127.0.0.1", 5433, 5433, 5432, "native"),
    ("native", "127.0.0.1", 5432, 5433, 5432, "native"),
    (" Native ", "127.0.0.1", 5432, 5433, 5432, "native"),
    ("docker", "127.0.0.1", 5433, 5433, 5432, "docker"),
    ("DOCKER", "db.example.com", 5432, 5433, 5432, "docker"),
]


@pytest.mark.parametrize(("explicit", "host", "port", "native", "docker", "expected"), CASES)
def test_backend_and_launcher_resolve_the_same(
    explicit: str | None, host: str, port: int, native: int, docker: int, expected: str
) -> None:
    kwargs = {"native_port": native, "docker_port": docker}
    assert dbm.resolve_db_mode(explicit, host, port, **kwargs) == expected
    assert dev.resolve_db_mode(explicit, host, port, **kwargs) == expected


@pytest.mark.parametrize("explicit", ["podman", "nativ", "docker-compose"])
def test_invalid_explicit_mode_is_rejected_by_both(explicit: str) -> None:
    kwargs = {"native_port": 5433, "docker_port": 5432}
    with pytest.raises(ValueError, match="DB_MODE"):
        dbm.resolve_db_mode(explicit, "127.0.0.1", 5432, **kwargs)
    with pytest.raises(ValueError, match="DB_MODE"):
        dev.resolve_db_mode(explicit, "127.0.0.1", 5432, **kwargs)


def _settings(url: str, mode: str | None = None, **extra: Any) -> Settings:
    # A raw string on purpose: the validator normalizes ` NATIVE ` like a .env value.
    return Settings(_env_file=None, database_url=url, db_mode=mode, **extra)  # type: ignore[arg-type]


NATIVE_URL = "postgresql+psycopg://journal:pw@127.0.0.1:5433/trading_journal"
DOCKER_URL = "postgresql+psycopg://journal:pw@127.0.0.1:5432/trading_journal"


def test_settings_mode_and_compose_port() -> None:
    assert dbm.db_mode(_settings(NATIVE_URL)) == "native"
    assert dbm.docker_compose_port(_settings(NATIVE_URL)) is None
    assert dbm.db_mode(_settings(DOCKER_URL)) == "docker"
    assert dbm.docker_compose_port(_settings(DOCKER_URL, postgres_port=5432)) == 5432
    assert dbm.docker_compose_port(_settings(DOCKER_URL, " NATIVE ")) is None
    assert dbm.db_mode(_settings(NATIVE_URL, "docker")) == "docker"
    assert dbm.db_mode(_settings(DOCKER_URL, "")) == "docker"
    assert dbm.db_mode(_settings(NATIVE_URL, native_pg_port=6000)) == "native"  # remote rule
    assert dbm.db_mode(_settings("not a url")) == "native"


def test_settings_reject_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        _settings(DOCKER_URL, "podman")


# --------------------------------------------------------------------------- launcher guard


def _has_docker(argv: object) -> bool:
    items = argv if isinstance(argv, list | tuple) else [argv]
    return any("docker" in str(item).lower() for item in items)


class NoDocker:
    """subprocess/shutil fakes that fail the test on any argv or lookup mentioning docker."""

    def __init__(self, sc: dict[str, list[tuple[int, str]]]) -> None:
        self.sc = sc
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if _has_docker(argv):
            pytest.fail(f"docker invoked in native mode: {argv}")
        self.calls.append(list(argv))
        if argv[0] == "sc.exe":
            code, out = self.sc[argv[1]].pop(0)
            return subprocess.CompletedProcess(argv, code, stdout=out.encode("utf-8"))
        pytest.fail(f"unexpected command: {argv}")

    def popen(self, argv: object, *_a: object, **_k: object) -> None:
        pytest.fail(f"process start not expected in native mode: {argv}")

    @staticmethod
    def which(name: str, *_a: object, **_k: object) -> str | None:
        if _has_docker(name):
            pytest.fail("shutil.which('docker') in native mode")
        return None


SC_STOPPED = "        STATE              : 1  STOPPED"
SC_RUNNING = "        STATE              : 4  RUNNING"


def _guard(
    monkeypatch: pytest.MonkeyPatch,
    sc: dict[str, list[tuple[int, str]]],
    reachable: list[bool],
) -> NoDocker:
    fake = NoDocker(sc)
    answers = iter(reachable)
    monkeypatch.setattr(dev, "IS_WINDOWS", True)
    monkeypatch.setattr(dev.subprocess, "run", fake.run)
    monkeypatch.setattr(dev.subprocess, "Popen", fake.popen)
    monkeypatch.setattr(dev.shutil, "which", fake.which)
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: next(answers, False))
    monkeypatch.setattr(dev.time, "sleep", lambda _s: None)
    monkeypatch.setattr(dev, "DB_TCP_TIMEOUT_S", 0.01)
    for name in ("ensure_docker_daemon", "docker_daemon_running", "docker_desktop_exe"):
        monkeypatch.setattr(dev, name, lambda *_a, _n=name: pytest.fail(f"{_n} called"))
    return fake


NATIVE_ENVS = [
    {"DATABASE_URL": NATIVE_URL},
    {"DATABASE_URL": NATIVE_URL, "DB_MODE": "native"},
    # explicit native even on the Docker port: still never Docker
    {"DATABASE_URL": DOCKER_URL, "DB_MODE": "native"},
]


@pytest.mark.parametrize("env", NATIVE_ENVS)
def test_native_reachable_never_docker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: dict[str, str]
) -> None:
    fake = _guard(monkeypatch, {}, [True])
    dev.ensure_db(env)
    assert fake.calls == []
    out = capsys.readouterr().out
    port = 5433 if ":5433/" in env["DATABASE_URL"] else 5432
    assert f"БД: native (127.0.0.1:{port})" in out
    assert "pw" not in out


@pytest.mark.parametrize("env", NATIVE_ENVS)
def test_native_stopped_service_started_never_docker(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    fake = _guard(
        monkeypatch, {"query": [(0, SC_STOPPED)], "start": [(0, "")]}, [False, False, True]
    )
    dev.ensure_db(env)
    assert [c[1] for c in fake.calls] == ["query", "start"]


@pytest.mark.parametrize("env", NATIVE_ENVS)
def test_native_missing_service_is_error_never_docker(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    _guard(monkeypatch, {"query": [(dev.SC_SERVICE_MISSING, "")]}, [False])
    with pytest.raises(dev.LauncherError) as error:
        dev.ensure_db(env)
    text = str(error.value)
    assert "native_pg.py status" in text
    assert "switch-back" in text
    assert "Docker не запускаю" in text


@pytest.mark.parametrize(
    "sc",
    [
        {"query": [(5, "")]},  # sc query failure
        {"query": [(0, "garbage")]},  # unparsable state
        {"query": [(0, SC_STOPPED)], "start": [(5, "")]},  # sc start failure (no admin)
        {"query": [(0, SC_RUNNING), (0, SC_RUNNING)]},  # running but port closed
    ],
)
def test_native_sc_failures_never_docker(
    monkeypatch: pytest.MonkeyPatch, sc: dict[str, list[tuple[int, str]]]
) -> None:
    _guard(monkeypatch, sc, [])
    with pytest.raises(dev.LauncherError, match="postgresql-x64-16"):
        dev.ensure_db({"DATABASE_URL": NATIVE_URL})


def test_native_mode_on_non_windows_never_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    _guard(monkeypatch, {}, [])
    monkeypatch.setattr(dev, "IS_WINDOWS", False)  # sc.exe cannot run -> "missing"
    with pytest.raises(dev.LauncherError, match=r"native_pg.py status"):
        dev.ensure_db({"DATABASE_URL": NATIVE_URL})


def test_invalid_db_mode_is_a_launcher_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _guard(monkeypatch, {}, [])
    with pytest.raises(dev.LauncherError, match="DB_MODE"):
        dev.ensure_db({"DATABASE_URL": NATIVE_URL, "DB_MODE": "podman"})


def test_docker_mode_prints_line_and_warns_about_native(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: True)
    env = {"DATABASE_URL": DOCKER_URL, "NATIVE_DATABASE_URL": NATIVE_URL}
    dev.ensure_db(env)
    out = capsys.readouterr().out
    assert "БД: Docker (127.0.0.1:5432)" in out
    assert "native_pg.py switch" in out
    assert "pw@" not in out
    dev.ensure_db({"DATABASE_URL": DOCKER_URL})
    assert "NATIVE_DATABASE_URL" not in capsys.readouterr().out


def test_docker_mode_keeps_compose_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    reachable = iter([False, True])
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: next(reachable))
    monkeypatch.setattr(dev.shutil, "which", lambda _n: "docker")
    monkeypatch.setattr(dev, "docker_daemon_running", lambda _d: True)
    monkeypatch.setattr(dev, "native_service_state", lambda _s: pytest.fail("no sc in docker"))
    monkeypatch.setattr(dev, "run_step", lambda cmd, *_a, **_k: calls.append(list(cmd)))
    dev.ensure_db({"DATABASE_URL": NATIVE_URL, "DB_MODE": "docker"})
    assert calls == [["docker", "compose", "up", "-d", "--wait", "db"]]


def test_load_env_lets_process_env_override_db_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=x\n", encoding="utf-8")
    monkeypatch.setattr(dev, "ENV_FILE", env_file)
    monkeypatch.setenv("DB_MODE", "docker")
    assert dev.load_env()["DB_MODE"] == "docker"


# --------------------------------------------------------------------------- backups / migrate


def _which_no_docker(name: str) -> str | None:
    if _has_docker(name):
        pytest.fail("which('docker') in native mode")
    return None


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(argv: object, *_a: object, **_k: object) -> None:
        pytest.fail(f"subprocess in native mode without tools: {argv}")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("shutil.which", _which_no_docker)


def test_dump_plan_native_without_pg_dump_is_error(tmp_path: Path) -> None:
    target = mig.parse_target(NATIVE_URL)
    with pytest.raises(mig.BackupError, match="native"):
        mig.dump_plan(
            target, tmp_path / "x", which=_which_no_docker, compose_dir=tmp_path, compose_port=None
        )
    docker_target = mig.parse_target(DOCKER_URL)  # same with the Docker port: still no Docker
    with pytest.raises(mig.BackupError, match="native"):
        mig.dump_plan(
            docker_target,
            tmp_path / "x",
            which=_which_no_docker,
            compose_dir=tmp_path,
            compose_port=None,
        )


def test_dump_plan_native_with_pg_dump_uses_host_tool(tmp_path: Path) -> None:
    def which(name: str) -> str | None:
        return "/pg/pg_dump" if name == "pg_dump" else _which_no_docker(name)

    plan = mig.dump_plan(
        mig.parse_target(NATIVE_URL), tmp_path / "x", which=which, compose_dir=tmp_path,
        compose_port=None,
    )  # fmt: skip
    assert plan.argv[0] == "/pg/pg_dump"
    assert not plan.to_stdout


def test_verify_native_without_pg_restore_is_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(b, "pg_tool", lambda _name: None)
    path = tmp_path / "archive.dump"
    path.write_bytes(b"PGDMP synthetic")
    with pytest.raises(b.BackupFailure, match="native"):
        b.PostgresTools(compose_port=None).verify_archive(path)
    with pytest.raises(b.BackupFailure, match="native"):
        b.PostgresTools.verify(path, docker_allowed=False)


def test_store_dump_native_without_pg_dump_never_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(b, "pg_tool", lambda _name: None)
    monkeypatch.setattr(b.PostgresTools, "_confirm_target", staticmethod(lambda *_a: None))
    monkeypatch.setattr(
        b.PostgresTools, "_confirm_compose", staticmethod(lambda *_a: pytest.fail("compose"))
    )
    with pytest.raises(mig.BackupError, match="native"):
        b.PostgresTools(compose_port=None).dump(NATIVE_URL, tmp_path / "x.dump")


def test_confirm_backup_target_native_never_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mig, "pg_tool", lambda _name: None)
    monkeypatch.setattr(b.PostgresTools, "_confirm_target", staticmethod(lambda *_a: None))
    monkeypatch.setattr(
        b.PostgresTools, "_confirm_compose", staticmethod(lambda *_a: pytest.fail("compose"))
    )
    with pytest.raises(mig.BackupError, match="native"):
        mig.confirm_backup_target(DOCKER_URL, None)


def test_migrate_native_mode_passes_no_compose_port(tmp_path: Path) -> None:
    import io

    ports: list[int | None] = []
    upgrades: list[object] = []
    deps = mig.Deps(
        runner=lambda *_a, **_k: pytest.fail("no dump without pg_dump"),
        which=_which_no_docker,
        backups_dir=tmp_path / "backups",
        compose_dir=tmp_path,
        read_revisions=lambda _cfg: mig.Revisions(frozenset({"a"}), frozenset({"b"})),
        upgrade=upgrades.append,
        verify_backup=lambda _p: None,
        confirm_target=lambda _url, port: ports.append(port),
    )
    settings = Settings(_env_file=None, database_url=NATIVE_URL, log_dir=tmp_path / "logs")
    out, err = io.StringIO(), io.StringIO()
    code = mig.main(settings=settings, deps=deps, out=out, err=err, configure_logging=False)
    assert code == 1
    assert ports == [None]
    assert upgrades == []
    assert "native" in err.getvalue()
    assert "pw@" not in err.getvalue()


def test_migrate_verify_backup_respects_native_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(b, "pg_tool", lambda _name: None)
    monkeypatch.setattr(mig, "get_settings", lambda: _settings(NATIVE_URL))
    path = tmp_path / "a.dump"
    path.write_bytes(b"PGDMP")
    with pytest.raises(b.BackupFailure, match="native"):
        mig.verify_backup(path)


def test_startup_check_native_without_tools_never_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(startup, "pg_tool", lambda _name: None)
    monkeypatch.setattr("app.tools.startup_check.shutil.which", _which_no_docker)
    monkeypatch.setattr(
        b.PostgresTools, "_confirm_compose", staticmethod(lambda *_a: pytest.fail("compose"))
    )
    with pytest.raises(startup.StartupFailure, match="native"):
        startup.check_backup_tools(_settings(NATIVE_URL))


def test_taxonomy_restore_native_without_pg_restore_never_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dry, "pg_tool", lambda _name: None)
    monkeypatch.setattr("app.tools.taxonomy_dry_run.shutil.which", _which_no_docker)
    target = mig.parse_target(DOCKER_URL)
    with pytest.raises(dry.DryRunError, match="native"):
        dry.restore(target, "trading_journal_taxdry_test", tmp_path / "x.dump", None)


def test_makefile_only_db_up_calls_docker_and_nothing_depends_on_it() -> None:
    makefile = (SCRIPT.parents[1] / "Makefile").read_text(encoding="utf-8")
    target = ""
    for line in makefile.splitlines():
        if line and not line.startswith(("\t", "#", " ")) and ":" in line and "=" not in line:
            target, _, prereqs = line.partition(":")
            assert "db-up" not in prereqs.split() or target == ".PHONY", target
        elif line.startswith("\t") and "docker" in line.lower():
            assert target == "db-up", f"{target} calls docker"

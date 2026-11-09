"""Pre-migration backup tool (app.tools.migrate) with fakes: no pg_dump, docker or DB."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.tools import migrate as mig

PASSWORD = "s3cr3t-DO-NOT-PRINT"  # noqa: S105 - fake test password
NOT_APPLIED = "Міграції НЕ застосовано"  # noqa: RUF001 - Ukrainian UI text
ROTATE_FAILED = "Не вдалося видалити стару резервну копію"  # noqa: RUF001
DEV_URL = f"postgresql+psycopg://journal:{PASSWORD}@127.0.0.1:5432/trading_journal"
TEST_URL = f"postgresql+psycopg://journal:{PASSWORD}@127.0.0.1:5432/trading_journal_test"
REMOTE_URL = f"postgresql+psycopg://journal:{PASSWORD}@db.example.com:5433/trading_journal"
NOW = datetime(2026, 11, 9, 14, 30, 5, tzinfo=UTC)
HEAD = "abc123"
EXPECTED_NAME = f"pre-migration-{HEAD}-20261109T143005Z.dump"
PENDING = mig.Revisions(current=frozenset({"old111"}), heads=frozenset({HEAD}))


@dataclass
class Call:
    argv: tuple[str, ...]
    env: dict[str, str]
    cwd: Path
    stdout: IO[bytes] | None


@dataclass
class FakeRunner:
    """Writes `payload` where the real tool would (the -f file or stdout)."""

    returncode: int = 0
    payload: bytes = b"PGDMP-fake-dump"
    stderr: str = ""
    raises: BaseException | None = None
    calls: list[Call] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
        stdout: IO[bytes] | None,
        timeout: float,
    ) -> mig.RunResult:
        self.calls.append(Call(tuple(argv), dict(env), cwd, stdout))
        if stdout is not None:
            stdout.write(self.payload)
        elif "-f" in argv:
            Path(argv[list(argv).index("-f") + 1]).write_bytes(self.payload)
        if self.raises is not None:  # after writing: a partial file exists, like a killed dump
            raise self.raises
        return mig.RunResult(self.returncode, self.stderr)


@dataclass
class FakeUpgrade:
    calls: list[Config] = field(default_factory=list)
    raises: Exception | None = None

    def __call__(self, cfg: Config) -> None:
        self.calls.append(cfg)
        if self.raises is not None:
            raise self.raises


def which_for(*available: str) -> Callable[[str], str | None]:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in available else None

    return which


def make_settings(tmp_path: Path, url: str = DEV_URL, compose_port: int = 5432) -> Settings:
    return Settings(
        _env_file=None, database_url=url, log_dir=tmp_path / "logs", postgres_port=compose_port
    )


@dataclass
class Env:
    tmp_path: Path
    runner: FakeRunner = field(default_factory=FakeRunner)
    upgrade: FakeUpgrade = field(default_factory=FakeUpgrade)
    available: tuple[str, ...] = ("pg_dump",)
    revisions: mig.Revisions | Exception = PENDING

    @property
    def backups(self) -> Path:
        return self.tmp_path / "backups"

    def deps(self) -> mig.Deps:
        def read(_cfg: Config) -> mig.Revisions:
            if isinstance(self.revisions, Exception):
                raise self.revisions
            return self.revisions

        return mig.Deps(
            runner=self.runner,
            which=which_for(*self.available),
            clock=lambda: NOW,
            backups_dir=self.backups,
            compose_dir=self.tmp_path,
            read_revisions=read,
            upgrade=self.upgrade,
        )

    def run(self, url: str = DEV_URL, compose_port: int = 5432) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = mig.main(
            settings=make_settings(self.tmp_path, url, compose_port),
            deps=self.deps(),
            out=out,
            err=err,
            configure_logging=False,
        )
        return code, out.getvalue(), err.getvalue()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def assert_no_secret(*texts: str) -> None:
    for text in texts:
        assert PASSWORD not in text


def test_no_pending_migrations_skips_backup_and_upgrade(env: Env) -> None:
    env.revisions = mig.Revisions(current=frozenset({HEAD}), heads=frozenset({HEAD}))

    code, out, err = env.run()

    assert code == 0
    assert "Міграцій немає" in out
    assert env.runner.calls == []
    assert env.upgrade.calls == []
    assert not env.backups.exists()
    assert_no_secret(out, err)


def test_test_database_skips_backup_and_upgrades(env: Env) -> None:
    code, out, _err = env.run(TEST_URL)

    assert code == 0
    assert "trading_journal_test" in out
    assert "пропускаю" in out
    assert env.runner.calls == []
    assert len(env.upgrade.calls) == 1
    assert not env.backups.exists()


def test_host_pg_dump_argv_env_and_printed_path(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGPASSWORD", "inherited-should-be-replaced")

    code, out, err = env.run()

    assert code == 0, err
    (call,) = env.runner.calls
    final = env.backups / EXPECTED_NAME
    partial = env.backups / (EXPECTED_NAME + ".partial")
    assert call.argv == (
        "/usr/bin/pg_dump", "-Fc", "--no-password", "-h", "127.0.0.1", "-p", "5432",
        "-U", "journal", "-d", "trading_journal", "-f", str(partial),
    )  # fmt: skip
    assert call.env["PGPASSWORD"] == PASSWORD
    assert call.env["PGCONNECT_TIMEOUT"] == "5"
    assert all(PASSWORD not in arg for arg in call.argv)
    assert final.read_bytes() == b"PGDMP-fake-dump"
    assert not partial.exists()
    assert str(final) in out
    assert len(env.upgrade.calls) == 1
    assert_no_secret(out, err)


def test_upgrade_gets_url_via_attributes_not_ini(env: Env) -> None:
    env.run()

    (cfg,) = env.upgrade.calls
    assert cfg.attributes["sqlalchemy.url"] == DEV_URL
    assert cfg.get_main_option("sqlalchemy.url") is None


def test_docker_fallback_argv_writes_stdout_to_file(env: Env) -> None:
    env.available = ("docker",)

    code, out, err = env.run()

    assert code == 0, err
    (call,) = env.runner.calls
    assert call.argv == (
        "/usr/bin/docker", "compose", "exec", "-T", "db",
        "pg_dump", "-Fc", "-U", "journal", "-d", "trading_journal",
    )  # fmt: skip
    assert call.cwd == env.tmp_path
    assert call.stdout is not None
    assert "PGPASSWORD" not in call.env
    assert (env.backups / EXPECTED_NAME).read_bytes() == b"PGDMP-fake-dump"
    assert len(env.upgrade.calls) == 1
    assert_no_secret(out, err)


@pytest.mark.parametrize(
    ("url", "available"),
    [(DEV_URL, ()), (REMOTE_URL, ("docker",))],
    ids=["local-no-tools", "remote-docker-only"],
)
def test_no_dump_tool_fails_without_upgrade(env: Env, url: str, available: tuple[str, ...]) -> None:
    env.available = available

    code, out, err = env.run(url)

    assert code == 1
    assert NOT_APPLIED in err
    assert "pg_dump" in err
    assert env.runner.calls == []
    assert env.upgrade.calls == []
    assert list(env.backups.glob("*")) == []
    assert_no_secret(out, err)


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(returncode=1, stderr="pg_dump: error: server version mismatch"),
        FakeRunner(payload=b""),
        FakeRunner(raises=subprocess.TimeoutExpired(["pg_dump"], 600)),
        FakeRunner(raises=FileNotFoundError("pg_dump")),
    ],
    ids=["nonzero", "empty", "timeout", "cannot-start"],
)
@pytest.mark.parametrize("tool", ["pg_dump", "docker"])
def test_dump_failure_removes_partial_and_skips_upgrade(
    env: Env, runner: FakeRunner, tool: str
) -> None:
    env.runner = replace(runner, calls=[])
    env.available = (tool,)

    code, out, err = env.run()

    assert code == 1
    assert NOT_APPLIED in err
    assert list(env.backups.glob("*")) == []
    assert env.upgrade.calls == []
    assert_no_secret(out, err)


def test_nonzero_exit_shows_stderr_tail(env: Env) -> None:
    env.runner = FakeRunner(returncode=1, stderr="pg_dump: error: server version mismatch\n")

    _, _, err = env.run()

    assert "server version mismatch" in err
    assert "кодом 1" in err


def test_db_unreachable_fails_without_backup(env: Env) -> None:
    env.revisions = OperationalError("connect", {}, Exception("connection refused"))

    code, out, err = env.run()

    assert code == 1
    assert "connection refused" in err
    assert env.runner.calls == []
    assert env.upgrade.calls == []
    assert_no_secret(out, err)


def test_invalid_url_fails_without_leaking(env: Env) -> None:
    code, out, err = env.run(f"not a url {PASSWORD}")

    assert code == 1
    assert "DATABASE_URL" in err
    assert_no_secret(out, err)


def test_upgrade_failure_returns_1_and_names_backup(env: Env) -> None:
    env.upgrade = FakeUpgrade(raises=RuntimeError("boom"))

    code, _, err = env.run()

    assert code == 1
    assert "boom" in err
    assert str(env.backups / EXPECTED_NAME) in err


def _stamp(i: int) -> str:
    return f"202611{i + 1:02d}T120000Z"


def test_rotation_keeps_ten_newest_and_ignores_other_files(env: Env) -> None:
    env.backups.mkdir()
    old = [env.backups / f"pre-migration-rev{i}-{_stamp(i)}.dump" for i in range(12)]
    for path in old:
        path.write_bytes(b"x")
    others = [
        env.backups / "manual.dump",
        env.backups / "pre-migration-notes.txt",
        env.backups / "pre-migration-weird.dump",  # no timestamp: never touched
        env.backups / f"pre-migration-rev0-{_stamp(0)}.dump.partial",
    ]
    for path in others:
        path.write_bytes(b"x")

    code, out, err = env.run()

    assert code == 0, err
    kept = sorted(p.name for p in env.backups.glob("pre-migration-*-*T*Z.dump"))
    expected = sorted([EXPECTED_NAME, *(p.name for p in old[-9:])])
    assert kept == expected
    assert all(p.exists() for p in others)
    assert "Видалено старих резервних копій: 3" in out


def test_rotate_backups_noop_when_ten_or_fewer(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"pre-migration-r-{_stamp(i)}.dump").write_bytes(b"x")

    assert mig.rotate_backups(tmp_path) == []
    assert len(list(tmp_path.iterdir())) == 10


def test_backup_name_uses_utc() -> None:
    from datetime import timedelta, timezone

    local = NOW.astimezone(timezone(timedelta(hours=1)))

    assert mig.backup_name(HEAD, local) == EXPECTED_NAME


def test_target_repr_hides_password() -> None:
    target = mig.parse_target(DEV_URL)

    assert PASSWORD not in repr(target)
    assert target.database == "trading_journal"
    assert target.is_local
    assert not target.is_test


def test_unknown_db_revision_fails_before_backup(env: Env) -> None:
    env.revisions = mig.Revisions(
        current=frozenset({"feedface"}), heads=frozenset({HEAD}), unknown=frozenset({"feedface"})
    )

    code, out, err = env.run()

    assert code == 1
    assert "feedface" in err
    assert "інша гілка" in err
    assert env.runner.calls == []
    assert env.upgrade.calls == []
    assert not env.backups.exists()
    assert_no_secret(out, err)


class FakeConn:
    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass


class FakeEngine:
    def connect(self) -> FakeConn:
        return FakeConn()

    def dispose(self) -> None:
        pass


class FakeContext:
    def get_current_heads(self) -> tuple[str, ...]:
        return ("deadbeef0000",)


def test_read_revisions_flags_unknown_db_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MigrationContext, "configure", lambda _conn: FakeContext())
    monkeypatch.setattr(mig, "create_engine", lambda *_a, **_k: FakeEngine())

    revs = mig.read_revisions(mig.alembic_config("postgresql+psycopg://u@localhost/d"))

    assert revs.unknown == frozenset({"deadbeef0000"})
    assert revs.heads  # the real script directory of this checkout


def test_docker_fallback_refused_when_port_differs_from_compose(env: Env) -> None:
    env.available = ("docker",)

    code, out, err = env.run(compose_port=5433)

    assert code == 1
    assert "POSTGRES_PORT=5433" in err
    assert NOT_APPLIED in err
    assert env.runner.calls == []
    assert env.upgrade.calls == []
    assert_no_secret(out, err)


def test_docker_fallback_uses_custom_compose_port(env: Env) -> None:
    env.available = ("docker",)
    url = DEV_URL.replace(":5432/", ":5433/")

    code, _, err = env.run(url, compose_port=5433)

    assert code == 0, err
    assert len(env.runner.calls) == 1


def test_cannot_open_partial_reports_io_error(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    env.available = ("docker",)

    def deny(self: Path, *_a: object, **_k: object) -> IO[bytes]:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "open", deny)

    code, _, err = env.run()

    assert code == 1
    assert "не вдалося записати файл резервної копії" in err
    assert "не вдалося запустити" not in err
    assert env.runner.calls == []
    assert env.upgrade.calls == []


def test_rotation_unlink_failure_warns_and_continues(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.backups.mkdir()
    for i in range(11):
        (env.backups / f"pre-migration-rev{i}-{_stamp(i)}.dump").write_bytes(b"x")
    locked = env.backups / f"pre-migration-rev0-{_stamp(0)}.dump"
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == locked.name:
            raise PermissionError("file in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)

    code, _, err = env.run()

    assert code == 0, err
    assert ROTATE_FAILED in err
    assert locked.exists()
    assert (env.backups / EXPECTED_NAME).exists()
    assert not (env.backups / f"pre-migration-rev1-{_stamp(1)}.dump").exists()
    assert len(env.upgrade.calls) == 1


@pytest.mark.parametrize("tool", ["pg_dump", "docker"])
def test_keyboard_interrupt_removes_partial_and_reraises(env: Env, tool: str) -> None:
    env.available = (tool,)
    env.runner = FakeRunner(raises=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        env.run()

    assert len(env.runner.calls) == 1
    assert list(env.backups.glob("*")) == []
    assert env.upgrade.calls == []

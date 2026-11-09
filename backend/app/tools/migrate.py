"""Apply Alembic migrations with a `pg_dump` backup first (M5-04a, PM rule 2026-11-09).

    (backend/)  uv run python -m app.tools.migrate

Used by `make migrate`, `make db-ensure`, `make dev` and `start.bat` (scripts/dev.py).
Steps: read the DB revision and the script head; nothing pending -> exit 0 without a backup.
A database whose name ends with `_test` is upgraded without a backup. Otherwise the DB is
dumped (custom format) to `<repo>/backups/pre-migration-<head>-<UTC timestamp>.dump`, only
the newest `KEEP_BACKUPS` such files are kept, and then `alembic upgrade head` runs. Any
backup failure stops here with exit code 1: the upgrade is NOT run.

`pg_dump` on PATH is preferred (password via PGPASSWORD in the child environment only).
Without it, a local DB is dumped through `docker compose exec -T db pg_dump` (the container
trusts its local socket). The password and the full URL are never put in argv, output or logs.
A raw `alembic upgrade head` bypasses this backup.
"""

# ruff: noqa: RUF001
# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Protocol, TextIO

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.config import REPO_ROOT, Settings, get_settings
from app.logging_setup import setup_logging

logger = logging.getLogger("app.tools.migrate")

BACKEND_DIR = REPO_ROOT / "backend"
BACKUPS_DIR = REPO_ROOT / "backups"  # gitignored
LOG_FILE = "migrate.log"
KEEP_BACKUPS = 10
CONNECT_TIMEOUT_S = 5
DUMP_TIMEOUT_S = 600.0
DEFAULT_PORT = 5432
TEST_DB_SUFFIX = "_test"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
COMPOSE_DB_SERVICE = "db"
BACKUP_PREFIX = "pre-migration-"
BACKUP_SUFFIX = ".dump"
PARTIAL_SUFFIX = ".partial"  # `<name>.dump.partial` never matches the rotation pattern
TIMESTAMP_FMT = "%Y%m%dT%H%M%SZ"
BACKUP_RE = re.compile(r"^pre-migration-.+-(?P<ts>\d{8}T\d{6}Z)\.dump$")
STDERR_TAIL_CHARS = 500
PREFIX = "[migrate] "

MSG: dict[str, str] = {
    "url_invalid": "Некоректний DATABASE_URL у .env (див. .env.example).",
    "db_unreachable": (
        "Не вдалося підключитися до БД {db} на {host}:{port}: {error}. Міграції не застосовано."
    ),
    "no_pending": "Міграцій немає: БД {db} уже на останній ревізії ({rev}).",
    "test_db_skip": "БД {db} тестова (*_test): резервну копію пропускаю.",
    "backup_start": "Роблю резервну копію БД {db} ({host}:{port}) через {tool}…",
    "backup_done": "Резервну копію збережено: {path}",
    "backup_failed": (
        "Не вдалося зробити резервну копію БД {db}: {reason}. "
        "Міграції НЕ застосовано. Деталі: {log}"
    ),
    "no_tool_local": (
        "не знайдено ні pg_dump, ні docker. Встановіть Docker Desktop або клієнт PostgreSQL 16"
    ),
    "no_tool_remote": (
        "не знайдено pg_dump (встановіть клієнт PostgreSQL 16; docker використовується "
        "лише для локальної БД на порту POSTGRES_PORT={compose_port})"
    ),
    "unknown_revision": (
        "БД {db} на ревізії {revs}, якої немає в цьому коді — інша гілка? "
        "Перейдіть на гілку з цією міграцією або оновіть код. "
        "Резервну копію не зроблено, міграції не застосовано."
    ),
    "dump_exit": "{tool} завершився з кодом {code}: {stderr}",
    "dump_empty": "файл резервної копії порожній",
    "dump_timeout": "{tool} не завершився за {timeout} с",
    "dump_cannot_start": "не вдалося запустити {tool}: {error}",
    "dump_io": "не вдалося записати файл резервної копії: {error}",
    "rotated": "Видалено старих резервних копій: {count} (зберігаю {keep} останніх).",
    "rotate_failed": "Не вдалося видалити стару резервну копію {path}: {error}",
    "upgrading": "Застосовую міграції БД {db}: {current} → {head}…",
    "upgrade_done": "Міграції застосовано: БД {db} на ревізії {head}.",
    "upgrade_failed": "Помилка міграції БД {db}: {error}. Деталі: {log}",
    "upgrade_failed_restore": "Резервна копія до міграції: {path}",
    "empty_revision": "(порожня БД)",
}


class MigrateError(Exception):
    """User-readable (Ukrainian) failure; never contains the password or the URL."""


class BackupError(MigrateError):
    """The backup failed: the upgrade must not run."""


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stderr: str


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
        stdout: IO[bytes] | None,
        timeout: float,
    ) -> RunResult: ...


@dataclass(frozen=True)
class DbTarget:
    host: str
    port: int
    user: str
    database: str
    password: str = field(repr=False)

    @property
    def is_test(self) -> bool:
        return self.database.endswith(TEST_DB_SUFFIX)

    @property
    def is_local(self) -> bool:
        return self.host.lower() in LOCAL_HOSTS


@dataclass(frozen=True)
class DumpPlan:
    """How to run the dump. `to_stdout`: the tool writes the dump to stdout (docker)."""

    tool: str
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(repr=False)
    cwd: Path
    to_stdout: bool


@dataclass(frozen=True)
class Revisions:
    current: frozenset[str]
    heads: frozenset[str]
    unknown: frozenset[str] = frozenset()  # current DB revisions missing from this checkout

    @property
    def pending(self) -> bool:
        return self.current != self.heads


def subprocess_runner(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: IO[bytes] | None,
    timeout: float,
) -> RunResult:
    """Run without a shell; stderr captured (pg_dump errors never contain the password)."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=stdout if stdout is not None else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return RunResult(result.returncode, result.stderr.decode("utf-8", errors="replace"))


# --- target / alembic -------------------------------------------------------------------


def parse_target(url: str) -> DbTarget:
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        # Fixed text only: the URL (and so the exception text) may contain the password.
        raise MigrateError(MSG["url_invalid"]) from None
    if not parsed.database:
        raise MigrateError(MSG["url_invalid"])
    return DbTarget(
        host=parsed.host or "localhost",
        port=parsed.port or DEFAULT_PORT,
        user=parsed.username or "",
        database=parsed.database,
        password=parsed.password or "",
    )


def alembic_config(url: str) -> Config:
    """No ini file: alembic.ini's fileConfig would replace our log handlers."""
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("path_separator", "os")
    cfg.attributes["sqlalchemy.url"] = url  # attributes: no ConfigParser `%` interpolation
    return cfg


def _is_known(script: ScriptDirectory, revision: str) -> bool:
    try:
        return script.get_revision(revision) is not None
    except CommandError:  # alembic wraps "Can't locate revision" in CommandError
        return False


def read_revisions(cfg: Config) -> Revisions:
    """Current DB heads (connect_timeout 5), the script heads, DB revisions unknown here."""
    script = ScriptDirectory.from_config(cfg)
    heads = frozenset(script.get_heads())
    engine = create_engine(
        str(cfg.attributes["sqlalchemy.url"]),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
    )
    try:
        with engine.connect() as conn:
            current = frozenset(MigrationContext.configure(conn).get_current_heads())
    finally:
        engine.dispose()
    unknown = frozenset(rev for rev in current if not _is_known(script, rev))
    return Revisions(current=current, heads=heads, unknown=unknown)


def upgrade_head(cfg: Config) -> None:
    command.upgrade(cfg, "head")


def _rev_label(revs: frozenset[str]) -> str:
    return "+".join(sorted(revs)) or MSG["empty_revision"]


# --- backup -----------------------------------------------------------------------------


def backup_name(revision: str, now: datetime) -> str:
    stamp = now.astimezone(UTC).strftime(TIMESTAMP_FMT)
    return f"{BACKUP_PREFIX}{revision}-{stamp}{BACKUP_SUFFIX}"


def _child_env(extra: Mapping[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PGPASSWORD"}
    env.update(extra)
    return env


def dump_plan(
    target: DbTarget,
    partial: Path,
    *,
    which: Callable[[str], str | None],
    compose_dir: Path,
    compose_port: int,
) -> DumpPlan:
    """Host pg_dump if on PATH; else docker compose when the URL points at the compose DB
    (local host and port == POSTGRES_PORT); else BackupError."""
    pg_dump = which("pg_dump")
    if pg_dump:
        argv: tuple[str, ...] = (
            pg_dump, "-Fc", "--no-password", "-h", target.host, "-p", str(target.port),
            "-U", target.user, "-d", target.database, "-f", str(partial),
        )  # fmt: skip
        extra = {"PGCONNECT_TIMEOUT": str(CONNECT_TIMEOUT_S)}
        if target.password:
            extra["PGPASSWORD"] = target.password
        return DumpPlan("pg_dump", argv, _child_env(extra), compose_dir, to_stdout=False)
    if not target.is_local or target.port != compose_port:
        raise BackupError(MSG["no_tool_remote"].format(compose_port=compose_port))
    docker = which("docker")
    if not docker:
        raise BackupError(MSG["no_tool_local"])
    argv = (
        docker, "compose", "exec", "-T", COMPOSE_DB_SERVICE,
        "pg_dump", "-Fc", "-U", target.user, "-d", target.database,
    )  # fmt: skip
    return DumpPlan("docker compose exec db pg_dump", argv, _child_env({}), compose_dir, True)


def _stderr_tail(text: str) -> str:
    tail = " ".join(text.split())[-STDERR_TAIL_CHARS:]
    return tail or "—"


def _open_partial(partial: Path) -> IO[bytes]:
    try:
        return partial.open("wb")
    except OSError as exc:
        raise BackupError(MSG["dump_io"].format(error=exc)) from exc


def run_dump(plan: DumpPlan, partial: Path, runner: Runner) -> None:
    """Run the plan into `partial`; BackupError on any failure (caller removes the file)."""
    try:
        if plan.to_stdout:
            out = _open_partial(partial)
            with out:
                result = runner(
                    plan.argv, env=plan.env, cwd=plan.cwd, stdout=out, timeout=DUMP_TIMEOUT_S
                )
        else:
            result = runner(
                plan.argv, env=plan.env, cwd=plan.cwd, stdout=None, timeout=DUMP_TIMEOUT_S
            )
    except subprocess.TimeoutExpired:
        timeout = f"{DUMP_TIMEOUT_S:.0f}"
        raise BackupError(MSG["dump_timeout"].format(tool=plan.tool, timeout=timeout)) from None
    except OSError as exc:
        raise BackupError(MSG["dump_cannot_start"].format(tool=plan.tool, error=exc)) from exc
    if result.returncode != 0:
        stderr = _stderr_tail(result.stderr)
        raise BackupError(
            MSG["dump_exit"].format(tool=plan.tool, code=result.returncode, stderr=stderr)
        )
    if not partial.is_file() or partial.stat().st_size == 0:
        raise BackupError(MSG["dump_empty"])


def make_backup(
    target: DbTarget, revision: str, deps: Deps, out: TextIO, *, compose_port: int
) -> Path:
    """Dump to `<name>.partial`, rename after success; the partial never survives a failure."""
    try:
        deps.backups_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(MSG["dump_io"].format(error=exc)) from exc
    final = deps.backups_dir / backup_name(revision, deps.clock())
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    plan = dump_plan(
        target, partial, which=deps.which, compose_dir=deps.compose_dir, compose_port=compose_port
    )
    _say(
        out,
        MSG["backup_start"].format(
            db=target.database, host=target.host, port=target.port, tool=plan.tool
        ),
    )
    logger.info("backup of %s via %s to %s", target.database, plan.tool, final)
    try:
        run_dump(plan, partial, deps.runner)
        partial.replace(final)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise BackupError(MSG["dump_io"].format(error=exc)) from exc
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return final


def rotate_backups(
    backups_dir: Path, keep: int = KEEP_BACKUPS, err: TextIO | None = None
) -> list[Path]:
    """Delete all but the newest `keep` pre-migration-*.dump (by name timestamp).

    Files that do not match the exact name pattern are never touched. Returns the deleted
    paths; a file that cannot be deleted is logged and skipped (the new backup exists)."""
    dated = [
        (match["ts"], path.name, path)
        for path in backups_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}")
        if path.is_file() and (match := BACKUP_RE.match(path.name))
    ]
    dated.sort(reverse=True)
    deleted: list[Path] = []
    for _, _, path in dated[keep:]:
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not delete old backup %s: %s", path, exc)
            text = MSG["rotate_failed"].format(path=path, error=exc)
            print(PREFIX + text, file=err or sys.stderr, flush=True)
            continue
        deleted.append(path)
    return deleted


# --- CLI --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Deps:
    runner: Runner = subprocess_runner
    which: Callable[[str], str | None] = shutil.which
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    backups_dir: Path = BACKUPS_DIR
    compose_dir: Path = REPO_ROOT
    read_revisions: Callable[[Config], Revisions] = read_revisions
    upgrade: Callable[[Config], None] = upgrade_head


def _say(out: TextIO, text: str) -> None:
    print(PREFIX + text, file=out, flush=True)


def _fail(err: TextIO, text: str) -> int:
    logger.error("%s", text)
    print(PREFIX + text, file=err, flush=True)
    return 1


def _connect_error(target: DbTarget, exc: SQLAlchemyError) -> str:
    # psycopg's message names host/user/db but never the password; the URL is not included.
    detail = " ".join(str(getattr(exc, "orig", None) or type(exc).__name__).split())
    return MSG["db_unreachable"].format(
        db=target.database, host=target.host, port=target.port, error=detail
    )


def _backup_step(
    target: DbTarget, revs: Revisions, deps: Deps, streams: tuple[TextIO, TextIO], port: int
) -> Path:
    out, err = streams
    path = make_backup(target, "+".join(sorted(revs.heads)), deps, out, compose_port=port)
    logger.info("backup written: %s", path)
    _say(out, MSG["backup_done"].format(path=path))
    deleted = rotate_backups(deps.backups_dir, err=err)
    if deleted:
        logger.info("rotation deleted %d old backup(s)", len(deleted))
        _say(out, MSG["rotated"].format(count=len(deleted), keep=KEEP_BACKUPS))
    return path


def _upgrade_step(
    cfg: Config, db: str, revs: Revisions, backup: Path | None, deps: Deps, log: Path
) -> tuple[bool, str]:
    """Run the upgrade; (ok, user message)."""
    try:
        deps.upgrade(cfg)
    except Exception as exc:
        logger.exception("alembic upgrade failed on %s", db)
        text = MSG["upgrade_failed"].format(db=db, error=exc, log=log)
        if backup is not None:
            text += " " + MSG["upgrade_failed_restore"].format(path=backup)
        return False, text
    return True, MSG["upgrade_done"].format(db=db, head=_rev_label(revs.heads))


def migrate(settings: Settings, deps: Deps, out: TextIO, err: TextIO) -> int:
    log = settings.log_dir_path / LOG_FILE
    try:
        target = parse_target(settings.database_url)
    except MigrateError as exc:
        return _fail(err, str(exc))
    db = target.database
    cfg = alembic_config(settings.database_url)
    try:
        revs = deps.read_revisions(cfg)
    except SQLAlchemyError as exc:
        return _fail(err, _connect_error(target, exc))
    if revs.unknown:
        return _fail(err, MSG["unknown_revision"].format(db=db, revs=_rev_label(revs.unknown)))
    if not revs.pending:
        _say(out, MSG["no_pending"].format(db=db, rev=_rev_label(revs.current)))
        return 0

    backup: Path | None = None
    if target.is_test:
        _say(out, MSG["test_db_skip"].format(db=db))
    else:
        try:
            backup = _backup_step(target, revs, deps, (out, err), settings.postgres_port)
        except BackupError as exc:
            return _fail(err, MSG["backup_failed"].format(db=db, reason=exc, log=log))

    current, head = _rev_label(revs.current), _rev_label(revs.heads)
    _say(out, MSG["upgrading"].format(db=db, current=current, head=head))
    ok, text = _upgrade_step(cfg, db, revs, backup, deps, log)
    if not ok:
        return _fail(err, text)
    _say(out, text)
    return 0


def main(
    *,
    settings: Settings | None = None,
    deps: Deps | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    configure_logging: bool = True,
) -> int:
    settings = settings or get_settings()
    out = out or sys.stdout
    err = err or sys.stderr
    for stream in (out, err):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")  # Ukrainian text on a cp1252 console
    if configure_logging:
        setup_logging(LOG_FILE, settings)
    return migrate(settings, deps or Deps(), out, err)


if __name__ == "__main__":
    raise SystemExit(main())

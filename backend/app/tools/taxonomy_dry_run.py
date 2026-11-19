"""Dry run of the M8-04..M8-08 journal taxonomy migration on a copy of the dev database.

    uv run --project backend python -m app.tools.taxonomy_dry_run

Steps (docs/api.md "Migration", DECISIONS 2026-11-19): `pg_dump` the database of
DATABASE_URL (host pg_dump, or `docker compose exec db` for the local compose DB, the same
helpers as the backups), restore it into a scratch database `<source>_taxdry_test`, run
`alembic upgrade head` there, print the counts per mapping (mapped / kept as legacy /
violations remapped / merged) and drop the scratch database (always, in `finally`). The
source database is only read by pg_dump; it is never changed. The same lines go to
`logs/taxonomy_dry_run.log`. No password or URL is printed.
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
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from sqlalchemy import Connection, create_engine, pool, text
from sqlalchemy.engine import make_url

from app.config import REPO_ROOT, Settings, get_settings
from app.logging_setup import setup_logging
from app.services.backups import PostgresTools
from app.tools.migrate import (
    COMPOSE_DB_SERVICE,
    CONNECT_TIMEOUT_S,
    DbTarget,
    MigrateError,
    alembic_config,
    parse_target,
    upgrade_head,
)

logger = logging.getLogger("app.tools.taxonomy_dry_run")

LOG_FILE = "taxonomy_dry_run.log"
SCRATCH_SUFFIX = "_taxdry_test"
TEST_SUFFIX = "_test"
RESTORE_TIMEOUT_S = 900.0
_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")
PREFIX = "[taxonomy-dry-run] "

Counts = Mapping[str, Mapping[str, int]]

# Old values / rows before the upgrade (on the scratch copy).
_BEFORE_SQL = {
    "setup_context": "SELECT count(*) FROM trades WHERE setup_context IS NOT NULL",
    "poi_type": "SELECT count(*) FROM trades WHERE poi_type IS NOT NULL",
    "fvg_kind": "SELECT count(*) FROM trades WHERE fvg_kind IS NOT NULL",
    "violations": (
        "SELECT count(*) FROM rule_violations WHERE rule_key IN ('daily_stop_loss_pct',"
        " 'daily_stop_profit_pct', 'weekly_stop_loss_pct', 'weekly_stop_profit_pct')"
    ),
}
# What is left in the old columns after the upgrade (= kept as legacy), and the new rows.
_AFTER_SQL = {
    "setup_context": _BEFORE_SQL["setup_context"],
    "poi_type": _BEFORE_SQL["poi_type"],
    "fvg_kind": _BEFORE_SQL["fvg_kind"],
    "violations": (
        "SELECT count(*) FROM rule_violations WHERE rule_key IN ('daily_risk', 'weekly_risk')"
    ),
}


class DryRunError(Exception):
    """User-readable failure (Ukrainian); never contains the password or the URL."""


# --- pure helpers (unit-tested) ---------------------------------------------------------


def report(counts: Counts) -> list[str]:
    """One line per mapping, input order: `setup_context: mapped=8, legacy=3`."""
    return [
        f"{name}: " + ", ".join(f"{counter}={number}" for counter, number in counters.items())
        for name, counters in counts.items()
    ]


def scratch_database_name(source_db: str) -> str:
    return f"{source_db}{SCRATCH_SUFFIX}"


def assert_safe_scratch(source_db: str, scratch_db: str) -> None:
    """The scratch DB is a plain identifier ending in `_test` and is not the source."""
    if not scratch_db or not _IDENTIFIER.fullmatch(scratch_db):
        raise ValueError(f"unsafe scratch database name: {scratch_db!r}")
    if not scratch_db.endswith(TEST_SUFFIX):
        raise ValueError(f"scratch database {scratch_db!r} must end with {TEST_SUFFIX!r}")
    if scratch_db == source_db:
        raise ValueError("the scratch database must differ from the source database")


def counts_from(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, dict[str, int]]:
    """Mapped = old values that left the old column; merged = old rows minus new rows."""
    out: dict[str, dict[str, int]] = {}
    for name in ("setup_context", "poi_type", "fvg_kind"):
        out[name] = {"mapped": before[name] - after[name], "legacy": after[name]}
    out["violations"] = {
        "remapped": before["violations"],
        "merged": before["violations"] - after["violations"],
    }
    return out


# --- database steps ---------------------------------------------------------------------


def _url_for(source_url: str, database: str) -> str:
    return make_url(source_url).set(database=database).render_as_string(hide_password=False)


def _admin(source_url: str, sql: str) -> None:
    engine = create_engine(
        source_url,
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
    )
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
    finally:
        engine.dispose()


def create_scratch(source_url: str, source_db: str, scratch_db: str) -> None:
    assert_safe_scratch(source_db, scratch_db)
    _admin(source_url, f'DROP DATABASE IF EXISTS "{scratch_db}" WITH (FORCE)')
    _admin(source_url, f'CREATE DATABASE "{scratch_db}"')


def drop_scratch(source_url: str, source_db: str, scratch_db: str) -> None:
    assert_safe_scratch(source_db, scratch_db)
    _admin(source_url, f'DROP DATABASE IF EXISTS "{scratch_db}" WITH (FORCE)')


def _restore_argv(target: DbTarget, scratch_db: str, dump: Path, compose_port: int) -> list[str]:
    tool = shutil.which("pg_restore")
    common = ["--no-owner", "--no-privileges", "--exit-on-error"]
    if tool:
        return [
            tool, *common, "--no-password", "-h", target.host, "-p", str(target.port),
            "-U", target.user, "-d", scratch_db, str(dump),
        ]  # fmt: skip
    docker = shutil.which("docker")
    if not docker or not target.is_local or target.port != compose_port:
        raise DryRunError("Немає pg_restore, а Docker недоступний для цієї БД")
    return [
        docker, "compose", "exec", "-T", COMPOSE_DB_SERVICE,
        "pg_restore", *common, "-U", target.user, "-d", scratch_db,
    ]  # fmt: skip


def restore(target: DbTarget, scratch_db: str, dump: Path, compose_port: int) -> None:
    """pg_restore the dump into the scratch DB (stdin for docker); DryRunError on failure."""
    argv = _restore_argv(target, scratch_db, dump, compose_port)
    env = {k: v for k, v in os.environ.items() if k != "PGPASSWORD"}
    if target.password:
        env["PGPASSWORD"] = target.password
    via_docker = argv[0] != shutil.which("pg_restore")
    try:
        with dump.open("rb") as stream:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no password in argv
                argv,
                cwd=REPO_ROOT,
                env=env,
                stdin=stream if via_docker else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=RESTORE_TIMEOUT_S,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DryRunError(f"pg_restore не вдалося: {type(exc).__name__}") from None
    if result.returncode != 0:
        tail = " ".join(result.stderr.decode("utf-8", errors="replace").split())[-500:]
        raise DryRunError(f"pg_restore завершився з кодом {result.returncode}: {tail}")


def _count(conn: Connection, queries: Mapping[str, str]) -> dict[str, int]:
    return {name: int(conn.execute(text(sql)).scalar_one()) for name, sql in queries.items()}


def measure(url: str, queries: Mapping[str, str]) -> dict[str, int]:
    engine = create_engine(
        url, poolclass=pool.NullPool, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
    )
    try:
        with engine.connect() as conn:
            return _count(conn, queries)
    finally:
        engine.dispose()


# --- CLI --------------------------------------------------------------------------------


def _say(out: TextIO, line: str) -> None:
    logger.info("%s", line)
    print(PREFIX + line, file=out, flush=True)


def _run_on_scratch(settings: Settings, target: DbTarget, scratch_db: str, out: TextIO) -> None:
    with tempfile.TemporaryDirectory(prefix="taxdry-") as tmp:
        dump = Path(tmp) / f"{target.database}.dump"
        _say(out, f"pg_dump БД {target.database} (лише читання)…")
        PostgresTools(compose_port=settings.postgres_port).dump(settings.database_url, dump)
        _say(out, f"Відновлюю копію у {scratch_db}…")
        restore(target, scratch_db, dump, settings.postgres_port)
    scratch_url = _url_for(settings.database_url, scratch_db)
    before = measure(scratch_url, _BEFORE_SQL)
    _say(out, f"alembic upgrade head на {scratch_db}…")
    upgrade_head(alembic_config(scratch_url))
    after = measure(scratch_url, _AFTER_SQL)
    for line in report(counts_from(before, after)):
        _say(out, line)


def dry_run(settings: Settings, out: TextIO, err: TextIO) -> int:
    try:
        target = parse_target(settings.database_url)
        scratch_db = scratch_database_name(target.database)
        assert_safe_scratch(target.database, scratch_db)
    except (MigrateError, ValueError) as exc:  # fixed texts only, never the URL
        print(PREFIX + f"Неправильна ціль: {exc}", file=err, flush=True)
        return 1
    created = False
    try:
        create_scratch(settings.database_url, target.database, scratch_db)
        created = True
        _run_on_scratch(settings, target, scratch_db, out)
    except Exception as exc:
        logger.exception("taxonomy dry run failed")
        print(PREFIX + f"Пробний прогін не вдався: {type(exc).__name__}: {exc}", file=err)
        return 1
    finally:
        if created:
            _drop_quietly(settings.database_url, target.database, scratch_db, out)
    _say(out, f"Готово. БД {target.database} не змінено.")
    return 0


def _drop_quietly(source_url: str, source_db: str, scratch_db: str, out: TextIO) -> None:
    try:
        drop_scratch(source_url, source_db, scratch_db)
        _say(out, f"Тимчасову БД {scratch_db} видалено.")
    except Exception:
        logger.exception("could not drop the scratch database %s", scratch_db)
        print(PREFIX + f"Не вдалося видалити тимчасову БД {scratch_db}", file=sys.stderr)


def main(*, settings: Settings | None = None, out: TextIO | None = None) -> int:
    settings = settings or get_settings()
    out = out or sys.stdout
    for stream in (out, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")  # Ukrainian text on a cp1252 console
    setup_logging(LOG_FILE, settings)
    return dry_run(settings, out, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

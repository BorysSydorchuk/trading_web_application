"""Move the journal's PostgreSQL from Docker to a native PostgreSQL 16 Windows service.

Run by the owner from the repo root (decision 2026-11-20, guide: docs/native-postgres.md):

    python -m uv run --project backend python scripts/native_pg.py <command>

Commands:
  secrets          generate the native superuser and `journal` passwords into .env
  install-command  print the elevated-PowerShell winget snippet (password read from .env)
  configure        localhost only, role `journal`, databases (ICU en-US), new superuser
                   password into .env; [--restart] (needs admin) [--no-rotate]
  copy             verified pg_dump of the Docker DB -> pg_restore into native -> compare
  switch           DATABASE_URL/TEST_DATABASE_URL -> native (Docker URLs kept as DOCKER_*)
  switch-back      DATABASE_URL/TEST_DATABASE_URL -> the kept Docker URLs
  status           active DB (docker/native), service state, both ports reachable?

Never prints a password or a URL. `.env` edits keep every other line byte-for-byte.
"""

# Only fixed commands (sc.exe, pg_restore) run; no user input reaches argv.
# ruff: noqa: S603, RUF001
# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
BACKUPS = ROOT / "backups"
COPY_MARKER = ROOT / "logs" / "native-pg-copy.json"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"

HOST = "127.0.0.1"
DEFAULT_NATIVE_PORT = 5433
DOCKER_PORT = 5432
SERVICE = "postgresql-x64-16"
SUPERUSER = "postgres"
APP_ROLE = "journal"
APP_DB = "trading_journal"
TEST_DB = "trading_journal_test"
CONNECT_TIMEOUT_S = 5
RESTORE_TIMEOUT_S = 600.0
SERVICE_TIMEOUT_S = 60.0
PASSWORD_BYTES = 32

K_PORT = "NATIVE_PG_PORT"
K_SUPER = "NATIVE_PG_SUPERUSER_PASSWORD"
K_NATIVE_URL = "NATIVE_DATABASE_URL"
K_NATIVE_TEST = "NATIVE_TEST_DATABASE_URL"
K_URL = "DATABASE_URL"
K_TEST = "TEST_DATABASE_URL"
K_DOCKER_URL = "DOCKER_DATABASE_URL"
K_DOCKER_TEST = "DOCKER_TEST_DATABASE_URL"
NATIVE_KEYS = (K_PORT, K_SUPER, K_NATIVE_URL, K_NATIVE_TEST)

WINGET_ID = "PostgreSQL.PostgreSQL.16"
# EDB installer options (installbuilder): unattended, no UI, our port and service name.
EDB_OPTIONS = (
    "--mode unattended --unattendedmodeui none --superpassword $pw "
    f"--serverport {DEFAULT_NATIVE_PORT} --servicename {SERVICE} "
    "--disable-components pgAdmin,stackbuilder"
)
SESSION_SETTINGS = (
    "SET TIME ZONE 'UTC'",
    "SET DateStyle = 'ISO, MDY'",
    "SET IntervalStyle = 'postgres'",
    "SET extra_float_digits = 1",
    "SET bytea_output = 'hex'",
)


class NativePgError(Exception):
    """Readable Ukrainian failure; never contains a password or a URL."""


def say(text: str) -> None:
    print(f"[native-pg] {text}", flush=True)


# --------------------------------------------------------------------------- .env editing


def _line_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :]
    key = stripped.partition("=")[0].strip()
    return key or None


def _raw_value(line: str) -> str:
    return line.rstrip("\r\n").partition("=")[2].strip()


def raw_env(text: str) -> dict[str, str]:
    """KEY -> raw value text (quotes kept) of the last assignment, as dotenv reads it."""
    return {
        key: _raw_value(line) for line in text.splitlines() if (key := _line_key(line)) is not None
    }


def unquote_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return raw[1:-1]
    return raw


def env_values(text: str) -> dict[str, str]:
    return {key: unquote_value(raw) for key, raw in raw_env(text).items()}


def set_env(text: str, updates: Mapping[str, str]) -> str:
    """`text` with each KEY=value set: first assignment replaced in place (its line ending
    kept), later duplicates dropped, missing keys appended. Other lines untouched."""
    ending = "\r\n" if "\r\n" in text else "\n"
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        key = _line_key(line)
        if key is None or key not in updates:
            out.append(line)
            continue
        if key in seen:
            continue
        seen.add(key)
        body = line.rstrip("\r\n")
        out.append(f"{key}={updates[key]}{line[len(body) :] or ending}")
    missing = [key for key in updates if key not in seen]
    if missing and out and not out[-1].endswith(("\n", "\r")):
        out[-1] += ending
    out.extend(f"{key}={updates[key]}{ending}" for key in missing)
    return "".join(out)


def read_env_text(path: Path) -> str:
    if not path.is_file():
        raise NativePgError(f"Не знайдено {path.name}. Запустіть спершу start.bat (створить .env).")
    return path.read_bytes().decode("utf-8")


def write_env_text(path: Path, text: str) -> None:
    """Atomic replace; bytes exactly as composed (no newline translation)."""
    tmp = path.with_name(path.name + ".native-pg.tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


# --------------------------------------------------------------------------- pure planning


def make_password(token: Callable[[int], str] = secrets.token_urlsafe) -> str:
    """URL-safe random password that never starts with `-` (installer would read an option)."""
    while True:
        value = token(PASSWORD_BYTES)
        if not value.startswith("-"):
            return value


def native_url(password: str, port: int, database: str, user: str = APP_ROLE) -> str:
    return (
        f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{HOST}:{port}/{quote(database, safe='')}"
    )


def secrets_updates(
    current: Mapping[str, str], *, force: bool, password: Callable[[], str] = make_password
) -> dict[str, str]:
    present = [key for key in NATIVE_KEYS if key in current]
    if present and not force:
        raise NativePgError(
            "У .env уже є " + ", ".join(present) + ". Нічого не змінено; щоб згенерувати нові "
            "паролі, додайте --force (лише ДО встановлення PostgreSQL або разом з configure)."
        )
    app_password = password()
    port = DEFAULT_NATIVE_PORT
    return {
        K_PORT: str(port),
        K_SUPER: password(),
        K_NATIVE_URL: native_url(app_password, port, APP_DB),
        K_NATIVE_TEST: native_url(app_password, port, TEST_DB),
    }


def switch_updates(raw: Mapping[str, str]) -> dict[str, str]:
    """DATABASE_URL/TEST_DATABASE_URL -> native; the Docker values kept once as DOCKER_*."""
    for key in (K_NATIVE_URL, K_NATIVE_TEST):
        if not raw.get(key):
            raise NativePgError(f"У .env немає {key}; спершу виконайте команду secrets.")
    for key in (K_URL, K_TEST):
        if not raw.get(key):
            raise NativePgError(f"У .env немає {key}; перемикати нічого.")
    if raw[K_URL] == raw[K_NATIVE_URL] and raw[K_TEST] == raw[K_NATIVE_TEST]:
        raise NativePgError("Застосунок уже працює з нативним PostgreSQL; нічого не змінено.")
    updates = {K_URL: raw[K_NATIVE_URL], K_TEST: raw[K_NATIVE_TEST]}
    if K_DOCKER_URL not in raw:
        updates[K_DOCKER_URL] = raw[K_URL]
    if K_DOCKER_TEST not in raw:
        updates[K_DOCKER_TEST] = raw[K_TEST]
    return updates


def switch_back_updates(raw: Mapping[str, str]) -> dict[str, str]:
    if not raw.get(K_DOCKER_URL) or not raw.get(K_DOCKER_TEST):
        raise NativePgError(
            f"У .env немає {K_DOCKER_URL}/{K_DOCKER_TEST} (switch ще не виконувався); "
            "нічого не змінено."
        )
    if raw.get(K_URL) == raw[K_DOCKER_URL] and raw.get(K_TEST) == raw[K_DOCKER_TEST]:
        raise NativePgError("Застосунок уже працює з Docker PostgreSQL; нічого не змінено.")
    return {K_URL: raw[K_DOCKER_URL], K_TEST: raw[K_DOCKER_TEST]}


def install_snippet() -> str:
    """PowerShell for an elevated window in the repo root; the password stays in `$pw`."""
    return "\n".join(
        [
            "$pw = ((Get-Content -Encoding utf8 .env | Where-Object { $_ -match "
            f"'^{K_SUPER}=' }}) -replace '^{K_SUPER}=', '').Trim()",
            'if (-not $pw) { Write-Host "Немає пароля в .env: виконайте secrets"; return }',
            f"winget install --id {WINGET_ID} -e --accept-package-agreements "
            f'--accept-source-agreements --override "{EDB_OPTIONS}"',
            "Remove-Variable pw",
        ]
    )


# --------------------------------------------------------------------------- comparison


@dataclass(frozen=True)
class Snapshot:
    counts: Mapping[str, int]
    checksums: Mapping[str, str]
    alembic: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    table: str
    source: str
    target: str

    @property
    def ok(self) -> bool:
        """Equal and present: a value missing on both sides is never a verified copy."""
        return self.source == self.target and self.source != MISSING


@dataclass(frozen=True)
class Comparison:
    rows: tuple[Row, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return bool(self.rows) and all(row.ok for row in self.rows)


MISSING = "—"


def compare(source: Snapshot, target: Snapshot) -> Comparison:
    """Row per table count, per checksum and the alembic revision; any mismatch -> not ok."""
    rows: list[Row] = []
    for table in sorted({*source.counts, *target.counts}):
        rows.append(
            Row(
                f"{table} (рядків)",
                str(source.counts.get(table, MISSING)),
                str(target.counts.get(table, MISSING)),
            )
        )
    for table in sorted({*source.checksums, *target.checksums}):
        rows.append(
            Row(
                f"{table} (md5)",
                source.checksums.get(table, MISSING),
                target.checksums.get(table, MISSING),
            )
        )
    rows.append(
        Row(
            "alembic_version",
            "+".join(source.alembic) or MISSING,
            "+".join(target.alembic) or MISSING,
        )
    )
    return Comparison(tuple(rows))


def format_comparison(result: Comparison) -> list[str]:
    width = max((len(row.table) for row in result.rows), default=10)
    lines = [f"{'таблиця'.ljust(width)}  {'Docker':>34}  {'native':>34}  стан"]
    for row in result.rows:
        state = "OK" if row.ok else "РІЗНИЦЯ"
        lines.append(f"{row.table.ljust(width)}  {row.source:>34}  {row.target:>34}  {state}")
    return lines


def checksum_tables(model_tables: Sequence[str]) -> list[str]:
    return sorted({*model_tables, "alembic_version"})


# --------------------------------------------------------------------------- dev.py reuse


def load_dev() -> ModuleType:
    """scripts/dev.py (stdlib launcher): sc.exe helpers, ports, the "app running" check."""
    spec = importlib.util.spec_from_file_location("tj_dev_for_native_pg", DEV_SCRIPT)
    if spec is None or spec.loader is None:
        raise NativePgError("Не знайдено scripts/dev.py.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dev.py dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def ensure_app_stopped(dev: Any) -> None:
    busy = dev.busy_ports(dev.APP_PORTS)
    if busy or dev.alive_records(dev.read_run_file(dev.RUN_FILE)) or dev.find_orphan_workers():
        ports = ", ".join(map(str, busy)) or "—"
        raise NativePgError(
            f"Застосунок або worker запущений (зайняті порти: {ports}). Зупиніть його "
            "(stop.bat) і запустіть команду знову; нічого не скопійовано."
        )


# --------------------------------------------------------------------------- database I/O


@dataclass(frozen=True)
class Conn:
    host: str
    port: int
    user: str
    database: str
    password: str = field(repr=False)


def conn_from_url(url: str) -> Conn:
    from app.tools.migrate import MigrateError, parse_target

    try:
        target = parse_target(url)
    except MigrateError:
        raise NativePgError("Некоректний URL бази даних у .env.") from None
    return Conn(target.host, target.port, target.user, target.database, target.password)


def connect(conn: Conn, *, autocommit: bool = False) -> Any:
    import psycopg

    try:
        return psycopg.connect(
            host=conn.host,
            port=conn.port,
            user=conn.user,
            password=conn.password,
            dbname=conn.database,
            connect_timeout=CONNECT_TIMEOUT_S,
            autocommit=autocommit,
        )
    except psycopg.Error as exc:
        # psycopg names host/user/db, never the password.
        detail = " ".join(str(exc).split())[:300]
        raise NativePgError(
            f"Не вдалося підключитися до {conn.database} на {conn.host}:{conn.port} "
            f"як {conn.user}: {detail}"
        ) from None


def snapshot(db: Any, model_tables: Sequence[str]) -> Snapshot:
    from psycopg import sql

    with db.cursor() as cur:
        for statement in SESSION_SETTINGS:
            cur.execute(statement)
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
        tables = [str(r[0]) for r in cur.fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            cur.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table)))
            counts[table] = int(cur.fetchone()[0])
        sums: dict[str, str] = {}
        for table in checksum_tables(model_tables):
            if table not in counts:
                continue
            cur.execute(
                sql.SQL(
                    "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text COLLATE \"C\"),"
                    " '')) FROM public.{} t"
                ).format(sql.Identifier(table))
            )
            sums[table] = str(cur.fetchone()[0])
        alembic: tuple[str, ...] = ()
        if "alembic_version" in counts:
            cur.execute("SELECT version_num FROM alembic_version ORDER BY 1")
            alembic = tuple(str(r[0]) for r in cur.fetchall())
    db.rollback()
    return Snapshot(counts, sums, alembic)


def database_exists(db: Any, name: str) -> bool:
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None


CREATE_DB_ICU = (
    "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8' "
    "LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LOCALE 'C'"
)
CREATE_DB_DEFAULT = "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'"


def create_database(db: Any, name: str) -> None:
    """ICU en-US collation (text ORDER BY close to Docker's en_US.utf8); if this server has
    no ICU support, the cluster's default locale with a printed warning."""
    import psycopg
    from psycopg import sql

    for template in (CREATE_DB_ICU, CREATE_DB_DEFAULT):
        statement = sql.SQL(template).format(sql.Identifier(name), sql.Identifier(APP_ROLE))
        try:
            with db.cursor() as cur:
                cur.execute(statement)
            return
        except psycopg.Error as exc:
            if template is CREATE_DB_DEFAULT:
                raise
            detail = " ".join(str(exc).split())[:200]
            say(
                f"УВАГА: ICU-локаль en-US недоступна ({detail}); створюю {name} з локаллю "
                "кластера за замовчуванням — порядок сортування тексту може відрізнятися "
                "від Docker."
            )


def public_relation_count(db: Any) -> int:
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public'"
        )
        return int(cur.fetchone()[0])


# --------------------------------------------------------------------------- settings from .env


@dataclass(frozen=True)
class Native:
    port: int
    superuser_password: str = field(repr=False)
    app: Conn
    test: Conn

    def superuser(self, database: str = "postgres") -> Conn:
        return Conn(HOST, self.port, SUPERUSER, database, self.superuser_password)


def native_settings(env: Mapping[str, str]) -> Native:
    missing = [key for key in NATIVE_KEYS if not env.get(key)]
    if missing:
        raise NativePgError("У .env немає " + ", ".join(missing) + "; спершу виконайте secrets.")
    try:
        port = int(env[K_PORT])
    except ValueError:
        raise NativePgError(f"{K_PORT} у .env має бути числом.") from None
    return Native(
        port, env[K_SUPER], conn_from_url(env[K_NATIVE_URL]), conn_from_url(env[K_NATIVE_TEST])
    )


def is_native(conn: Conn, port: int) -> bool:
    return conn.host.lower() in {"localhost", "127.0.0.1", "::1"} and conn.port == port


# --------------------------------------------------------------------------- service (sc.exe)


def service_state(dev: Any) -> str | None:
    state = dev.native_service_state(SERVICE)
    return str(state) if state is not None else None


def wait_state(dev: Any, wanted: str, timeout_s: float = SERVICE_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if service_state(dev) == wanted:
            return True
        time.sleep(1)
    return False


ADMIN_HINT = (
    "Відкрийте PowerShell від імені адміністратора (Win → «PowerShell» → «Запуск від імені "
    "адміністратора») і повторіть команду, або перезапустіть службу «{service}» у services.msc."
)


def restart_service(dev: Any, port: int) -> None:
    say(f"Перезапускаю службу «{SERVICE}»…")
    code, _out = dev.run_sc(["stop", SERVICE])
    if code not in (0, 1062):  # 1062: service not started
        raise NativePgError(
            f"sc stop не вдався (код {code}). " + ADMIN_HINT.format(service=SERVICE)
        )
    if not wait_state(dev, "STOPPED"):
        raise NativePgError(f"Служба «{SERVICE}» не зупинилася за {SERVICE_TIMEOUT_S:.0f} с.")
    code, _out = dev.run_sc(["start", SERVICE])
    if code != 0:
        raise NativePgError(
            f"sc start не вдався (код {code}). " + ADMIN_HINT.format(service=SERVICE)
        )
    if not dev.wait_tcp(HOST, port, SERVICE_TIMEOUT_S):
        raise NativePgError(f"Після перезапуску {HOST}:{port} недоступний; див. services.msc.")
    say(f"Службу «{SERVICE}» перезапущено, {HOST}:{port} доступний.")


def set_autostart(dev: Any) -> None:
    code, _out = dev.run_sc(["config", SERVICE, "start=", "auto"])
    if code == 0:
        say(f"Служба «{SERVICE}»: тип запуску «Автоматично».")
    else:
        say(
            f"УВАГА: не вдалося встановити автозапуск служби (код {code}). "
            + ADMIN_HINT.format(service=SERVICE)
        )


# --------------------------------------------------------------------------- commands


def cmd_secrets(env_file: Path, force: bool) -> int:
    text = read_env_text(env_file)
    updates = secrets_updates(raw_env(text), force=force)
    write_env_text(env_file, set_env(text, updates))
    say("Паролі згенеровано і записано в .env: " + ", ".join(updates) + " (значення не показую).")
    return 0


def cmd_install_command() -> int:
    say("Відкрийте PowerShell ВІД ІМЕНІ АДМІНІСТРАТОРА в корені репозиторію і вставте:")
    print(install_snippet(), flush=True)
    say(
        "Пароль читається з .env у змінну $pw і не друкується; після встановлення "
        "змінна видаляється."
    )
    return 0


def _configure_server(db: Any, native: Native) -> bool:
    """listen_addresses + role; True when a restart is pending."""
    from psycopg import sql

    with db.cursor() as cur:
        cur.execute("SHOW listen_addresses")
        if str(cur.fetchone()[0]) != "localhost":
            cur.execute("ALTER SYSTEM SET listen_addresses = 'localhost'")
            cur.execute("SELECT pg_reload_conf()")
            say("listen_addresses = 'localhost' записано (ALTER SYSTEM).")
        else:
            say("listen_addresses уже 'localhost'.")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL(verb + " ROLE {} WITH LOGIN CREATEDB PASSWORD {}").format(
                sql.Identifier(APP_ROLE), sql.Literal(native.app.password)
            )
        )
        say(f"Роль {APP_ROLE}: {'пароль оновлено' if verb == 'ALTER' else 'створено'}.")
        cur.execute("SELECT pending_restart FROM pg_settings WHERE name = 'listen_addresses'")
        return bool(cur.fetchone()[0])


def rotate_superuser(
    env_file: Path,
    old_password: str,
    alter: Callable[[str], None],
    password: Callable[[], str] = make_password,
) -> None:
    """New superuser password: ALTER ROLE first, `.env` only after it succeeded; if the
    `.env` write then fails, the old password is set back so the two never disagree."""
    new_password = password()
    alter(new_password)
    try:
        text = read_env_text(env_file)
        write_env_text(env_file, set_env(text, {K_SUPER: new_password}))
    except (OSError, UnicodeError, NativePgError) as exc:
        alter(old_password)
        raise NativePgError(
            f"Не вдалося записати новий пароль postgres у .env ({type(exc).__name__}); "
            "пароль повернено до попереднього."
        ) from None
    say(
        "Пароль суперкористувача postgres змінено і записано в .env (значення не показую). "
        "Старий пароль міг лишитися в журналі інсталятора в %TEMP% (install-postgresql.log, "
        "журнали winget) — він більше не дійсний."
    )


def _alter_superuser(db: Any) -> Callable[[str], None]:
    from psycopg import sql

    def alter(new_password: str) -> None:
        with db.cursor() as cur:
            cur.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                    sql.Identifier(SUPERUSER), sql.Literal(new_password)
                )
            )

    return alter


def cmd_configure(env_file: Path, restart: bool, rotate: bool = True) -> int:
    native = native_settings(env_values(read_env_text(env_file)))
    dev = load_dev()
    state = service_state(dev)
    say(f"Служба «{SERVICE}»: {state or 'не знайдена'}.")
    with connect(native.superuser(), autocommit=True) as db:
        pending = _configure_server(db, native)
        for name in (APP_DB, TEST_DB):
            if database_exists(db, name):
                say(f"База {name} уже існує.")
            else:
                create_database(db, name)
                say(f"Базу {name} створено (власник {APP_ROLE}, UTF8).")
        if rotate:
            rotate_superuser(env_file, native.superuser_password, _alter_superuser(db))
    set_autostart(dev)
    if pending and restart:
        restart_service(dev, native.port)
    elif pending:
        say(
            "Потрібен перезапуск служби, щоб застосувати listen_addresses: повторіть "
            "configure --restart у PowerShell від імені адміністратора."
        )
    return 0


def _dump_source(source_url: str, compose_port: int, now: datetime) -> Path:
    from app.services.backups import BackupFailure, PostgresTools
    from app.tools.migrate import MigrateError

    BACKUPS.mkdir(parents=True, exist_ok=True)
    final = BACKUPS / f"pre-native-{now.strftime('%Y%m%dT%H%M%SZ')}.dump"
    partial = final.with_name(final.name + ".partial")
    tools = PostgresTools(compose_port=compose_port)
    say("Роблю pg_dump поточної (Docker) бази…")
    try:
        tools.dump(source_url, partial)
        tools.verify(partial)  # pg_restore --list + full data read
        partial.replace(final)
    except (BackupFailure, MigrateError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise NativePgError(f"Резервна копія не вдалася: {exc}. Нічого не скопійовано.") from None
    say(f"Резервну копію перевірено (pg_restore --list): {final}")
    return final


def _prepare_target(native: Native, replace: bool) -> None:
    with connect(native.app) as db:
        relations = public_relation_count(db)
    if relations == 0:
        return
    if not replace:
        raise NativePgError(
            f"Нативна база {APP_DB} не порожня ({relations} об'єктів). Нічого не змінено; "
            "щоб перезаписати її копією з Docker, додайте --replace."
        )
    from psycopg import sql

    say(f"--replace: перестворюю нативну базу {APP_DB}…")
    with connect(native.superuser(), autocommit=True) as db, db.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(APP_DB)))
        create_database(db, APP_DB)


def restore_argv(tool: str, conn: Conn, dump: Path) -> list[str]:
    return [
        tool, "--no-owner", f"--role={APP_ROLE}", "--no-privileges", "--exit-on-error",
        "--single-transaction", "--no-password", "-h", conn.host, "-p", str(conn.port),
        "-U", conn.user, "-d", conn.database, str(dump),
    ]  # fmt: skip


def _restore(native: Native, dump: Path) -> None:
    from app.system.pg_tools import pg_tool

    tool = pg_tool("pg_restore")
    if not tool:
        raise NativePgError("Не знайдено pg_restore (нативний PostgreSQL 16 встановлено?).")
    env = {k: v for k, v in os.environ.items() if k != "PGPASSWORD"}
    env["PGPASSWORD"] = native.app.password
    say(f"pg_restore у нативну базу {APP_DB}…")
    try:
        result = subprocess.run(
            restore_argv(tool, native.app, dump),
            env=env,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=RESTORE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativePgError(f"pg_restore не вдалося запустити: {type(exc).__name__}") from None
    if result.returncode:
        tail = " ".join(result.stderr.decode("utf-8", errors="replace").split())[-500:]
        raise NativePgError(f"pg_restore завершився з кодом {result.returncode}: {tail}")


def _ensure_test_db(native: Native) -> None:
    with connect(
        Conn(HOST, native.port, APP_ROLE, "postgres", native.app.password), autocommit=True
    ) as db:
        if database_exists(db, TEST_DB):
            return
        create_database(db, TEST_DB)
        say(f"Базу {TEST_DB} створено (тести самі створюють схему).")


def _model_tables() -> list[str]:
    from app.models import Base

    return sorted(Base.metadata.tables)


def cmd_copy(env_file: Path, replace: bool) -> int:
    env = env_values(read_env_text(env_file))
    native = native_settings(env)
    source_url = env.get(K_DOCKER_URL) or env.get(K_URL, "")
    if not source_url:
        raise NativePgError(f"У .env немає {K_URL}.")
    source = conn_from_url(source_url)
    if is_native(source, native.port):
        raise NativePgError("Джерело копіювання вказує на нативний сервер; нічого не скопійовано.")
    ensure_app_stopped(load_dev())
    COPY_MARKER.unlink(missing_ok=True)  # an older verified copy no longer counts
    now = datetime.now(UTC)
    dump = _dump_source(source_url, int(env.get("POSTGRES_PORT") or DOCKER_PORT), now)
    _prepare_target(native, replace)
    _restore(native, dump)
    _ensure_test_db(native)
    tables = _model_tables()
    with connect(source) as src, connect(native.app) as dst:
        result = compare(snapshot(src, tables), snapshot(dst, tables))
    for line in format_comparison(result):
        print(line, flush=True)
    if not result.ok:
        say("РІЗНИЦЯ між Docker і нативною базою. НЕ перемикайтеся (switch); див. таблицю вище.")
        return 1
    COPY_MARKER.parent.mkdir(parents=True, exist_ok=True)
    COPY_MARKER.write_text(
        json.dumps({"verified_at": now.isoformat(), "dump": str(dump)}), encoding="utf-8"
    )
    say("Копію перевірено: усі таблиці, контрольні суми й ревізія alembic збігаються.")
    return 0


def cmd_switch(env_file: Path, force: bool) -> int:
    if not COPY_MARKER.is_file() and not force:
        raise NativePgError(
            "Немає підтвердженої копії (команда copy). Нічого не змінено; "
            "--force перемикає без неї."
        )
    text = read_env_text(env_file)
    updates = switch_updates(raw_env(text))
    write_env_text(env_file, set_env(text, updates))
    say(
        "Перемкнено на нативний PostgreSQL (DATABASE_URL, TEST_DATABASE_URL). Docker-адреси "
        "збережено як DOCKER_DATABASE_URL / DOCKER_TEST_DATABASE_URL. Запустіть start.bat."
    )
    return 0


def cmd_switch_back(env_file: Path) -> int:
    text = read_env_text(env_file)
    write_env_text(env_file, set_env(text, switch_back_updates(raw_env(text))))
    say(
        "Повернено Docker PostgreSQL (DATABASE_URL, TEST_DATABASE_URL). Запустіть Docker "
        "Desktop, потім start.bat."
    )
    return 0


def describe_active(url: str, native_port: int, docker_port: int) -> str:
    if not url:
        return "не задано"
    try:
        conn = conn_from_url(url)
    except NativePgError:
        return "некоректний URL"
    if is_native(conn, native_port):
        return f"native (порт {conn.port})"
    if is_native(conn, docker_port):
        return f"docker (порт {conn.port})"
    return f"інший сервер ({conn.host}:{conn.port})"


def cmd_status(env_file: Path) -> int:
    env = env_values(read_env_text(env_file))
    dev = load_dev()
    native_port = int(env.get(K_PORT) or DEFAULT_NATIVE_PORT)
    docker_port = int(env.get("POSTGRES_PORT") or DOCKER_PORT)
    say(f"Активна БД застосунку: {describe_active(env.get(K_URL, ''), native_port, docker_port)}")
    say(f"Тестова БД: {describe_active(env.get(K_TEST, ''), native_port, docker_port)}")
    say(f"Служба «{SERVICE}»: {service_state(dev) or 'не знайдена'}")
    for label, port in (("Docker", docker_port), ("native", native_port)):
        reachable = "доступний" if dev.tcp_reachable(HOST, port) else "недоступний"
        say(f"{label} {HOST}:{port}: {reachable}")
    say(f"Підтверджена копія: {'так' if COPY_MARKER.is_file() else 'ні'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Перехід на нативний PostgreSQL 16.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("secrets").add_argument("--force", action="store_true")
    sub.add_parser("install-command")
    configure = sub.add_parser("configure")
    configure.add_argument("--restart", action="store_true")
    configure.add_argument("--no-rotate", action="store_true")
    sub.add_parser("copy").add_argument("--replace", action="store_true")
    sub.add_parser("switch").add_argument("--force", action="store_true")
    sub.add_parser("switch-back")
    sub.add_parser("status")
    return parser


def run(args: argparse.Namespace, env_file: Path) -> int:
    commands: dict[str, Callable[[], int]] = {
        "secrets": lambda: cmd_secrets(env_file, args.force),
        "install-command": cmd_install_command,
        "configure": lambda: cmd_configure(env_file, args.restart, not args.no_rotate),
        "copy": lambda: cmd_copy(env_file, args.replace),
        "switch": lambda: cmd_switch(env_file, args.force),
        "switch-back": lambda: cmd_switch_back(env_file),
        "status": lambda: cmd_status(env_file),
    }
    return commands[args.command]()


def main(argv: Sequence[str] | None = None, env_file: Path = ENV_FILE) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return run(args, env_file)
    except NativePgError as exc:
        say(f"ПОМИЛКА: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

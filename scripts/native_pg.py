"""Move the journal's PostgreSQL from Docker to a native PostgreSQL 16 Windows service.

Run by the owner from the repo root (decision 2026-11-20, guide: docs/native-postgres.md):

    python -m uv run --project backend python scripts/native_pg.py <command>

Commands:
  secrets          generate the native superuser and `journal` passwords into .env
  install-command  print the elevated-PowerShell winget snippet (password read from .env)
  configure        localhost only, role `journal`, databases (ICU en-US, Cyrillic smoke
                   test), new superuser password into .env; [--restart] [--no-rotate]
  copy             verified pg_dump of the Docker DB -> pg_restore into native -> compare
  switch           DATABASE_URL/TEST_DATABASE_URL -> native (Docker URLs kept as DOCKER_*)
  switch-back      DATABASE_URL/TEST_DATABASE_URL -> the kept Docker URLs
  status           active DB (docker/native), service state, both ports reachable?

Never prints a password or a URL; role passwords reach the server only as SCRAM verifiers.
`.env` editing lives in scripts/native_pg_env.py.
"""

# Only fixed commands (sc.exe, pg_restore) run; no user input reaches argv.
# ruff: noqa: S603, RUF001
# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from native_pg_compare import (
    ERROR_SUMMARY_CHARS,
    Snapshot,
    checksum_tables,
    compare,
    format_comparison,
    restore_error_summary,
)
from native_pg_env import (
    APP_DB,
    APP_ROLE,
    DEFAULT_NATIVE_PORT,
    HOST,
    K_DOCKER_URL,
    K_MODE,
    K_NATIVE_TEST,
    K_NATIVE_URL,
    K_PORT,
    K_SUPER,
    K_SUPER_NEW,
    K_TEST,
    K_URL,
    NATIVE_KEYS,
    NATIVE_SERVICE,
    TEST_DB,
    NativePgError,
    backup_env_file,
    env_values,
    fingerprint,
    install_snippet,
    port_value,
    raw_env,
    read_env_text,
    recover_rotation,
    rotate_superuser,
    say,
    secrets_updates,
    set_env,
    switch_back_updates,
    switch_updates,
    write_env_text,
)

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
BACKUPS = ROOT / "backups"
COPY_MARKER = ROOT / "logs" / "native-pg-copy.json"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"

DOCKER_PORT = 5432
SERVICE = NATIVE_SERVICE
SUPERUSER = "postgres"
CONNECT_TIMEOUT_S = 5
RESTORE_TIMEOUT_S = 600.0
SERVICE_TIMEOUT_S = 60.0

SESSION_SETTINGS = (
    "SET TIME ZONE 'UTC'",
    "SET DateStyle = 'ISO, MDY'",
    "SET IntervalStyle = 'postgres'",
    "SET extra_float_digits = 1",
    "SET bytea_output = 'hex'",
)
# Database variants, tried in order until one is created and passes TEXT_SMOKE_SQL.
CREATE_DB_ICU = (
    "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8' "
    "LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LOCALE 'C'"
)
CREATE_DB_ICU_CTYPE = (
    "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8' "
    "LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LC_COLLATE 'C' LC_CTYPE {}"
)
CREATE_DB_DEFAULT = "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'"
CTYPE_FALLBACKS = ("en-US", "en_US.UTF-8")  # UTF-8 capable LC_CTYPE names (Windows, libc)
TEXT_SMOKE_SQL = "SELECT lower('ЖУРНАЛ Є') = 'журнал є' AND 'Журнал' ILIKE '%журнал%'"


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
            "(stop.bat) і запустіть команду знову; нічого не змінено."
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


def _detail(exc: BaseException) -> str:
    # psycopg/server messages name host/user/db, never the password.
    return " ".join(str(exc).split())[:ERROR_SUMMARY_CHARS]


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
        raise NativePgError(
            f"Не вдалося підключитися до {conn.database} на {conn.host}:{conn.port} "
            f"як {conn.user}: {_detail(exc)}"
        ) from None


OpenDb = Callable[[str], AbstractContextManager[Any]]


def snapshot(db: Any, model_tables: Sequence[str], *, checksums: bool = True) -> Snapshot:
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
        # string_agg builds one text value per table: fine for a personal journal, but it
        # would hit PostgreSQL's 1 GB value limit on a table with more than ~1 GB of text.
        for table in checksum_tables(model_tables) if checksums else []:
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


def source_fingerprint(url: str) -> str:
    with connect(conn_from_url(url)) as db:
        snap = snapshot(db, [], checksums=False)
    return fingerprint(snap.counts, snap.alembic)


def database_exists(db: Any, name: str) -> bool:
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None


def public_relation_count(db: Any) -> int:
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public'"
        )
        return int(cur.fetchone()[0])


def text_semantics_ok(open_db: OpenDb, name: str) -> bool:
    """Cyrillic lower() and ILIKE behave like on Docker's en_US.utf8."""
    with open_db(name) as db, db.cursor() as cur:
        cur.execute(TEXT_SMOKE_SQL)
        return bool(cur.fetchone()[0])


def _execute(db: Any, statement: Any) -> str | None:
    """Run DDL; the error detail on failure (autocommit: the session stays usable)."""
    import psycopg

    try:
        with db.cursor() as cur:
            cur.execute(statement)
    except psycopg.Error as exc:
        return _detail(exc)
    return None


def drop_database(db: Any, name: str) -> None:
    from psycopg import sql

    error = _execute(db, sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    if error:
        raise NativePgError(f"Не вдалося видалити порожню базу {name}: {error}")


def _create_variants(name: str) -> list[Any]:
    from psycopg import sql

    ident, owner = sql.Identifier(name), sql.Identifier(APP_ROLE)
    return [
        sql.SQL(CREATE_DB_ICU).format(ident, owner),
        *(
            sql.SQL(CREATE_DB_ICU_CTYPE).format(ident, owner, sql.Literal(c))
            for c in CTYPE_FALLBACKS
        ),
        sql.SQL(CREATE_DB_DEFAULT).format(ident, owner),
    ]


def create_database(db: Any, name: str, open_db: OpenDb) -> None:
    """Create `name` (ICU en-US first) and keep the first variant whose Cyrillic smoke test
    passes; a failed variant's (empty) database is dropped before the next one."""
    for number, statement in enumerate(_create_variants(name), start=1):
        error = _execute(db, statement)
        if error:
            say(f"УВАГА: варіант {number} створення {name} не вдався ({error}); пробую наступний.")
            continue
        if text_semantics_ok(open_db, name):
            if number > 1:
                say(
                    f"УВАГА: {name} створено варіантом {number}; сортування тексту може трохи "
                    "відрізнятися від Docker."
                )
            return
        say(f"УВАГА: у варіанті {number} lower()/ILIKE для кирилиці не працюють; пробую наступний.")
        drop_database(db, name)
    raise NativePgError(
        f"Не вдалося створити {name} з робочою кирилицею (lower/ILIKE). Нічого не скопійовано; "
        "надішліть вивід вище."
    )


def ensure_database(db: Any, name: str, open_db: OpenDb) -> None:
    """Existing DB must pass the smoke test; an empty failing one is recreated."""
    if not database_exists(db, name):
        create_database(db, name, open_db)
        say(f"Базу {name} створено (власник {APP_ROLE}, UTF8).")
        return
    if text_semantics_ok(open_db, name):
        say(f"База {name} уже існує (кирилиця OK).")
        return
    with open_db(name) as target:
        relations = public_relation_count(target)
    if relations:
        raise NativePgError(
            f"У базі {name} lower()/ILIKE для кирилиці не працюють, а вона не порожня "
            f"({relations} об'єктів). Нічого не змінено; потрібне ручне рішення."
        )
    say(f"База {name} порожня, але кирилиця не працює — перестворюю.")
    drop_database(db, name)
    create_database(db, name, open_db)


def scram_verifier(db: Any, password: str, user: str) -> str:
    """Client-side SCRAM-SHA-256 verifier: the plaintext never reaches the server (or its log)."""
    raw = db.pgconn.encrypt_password(
        password.encode("utf-8"), user.encode("utf-8"), b"scram-sha-256"
    )
    return bytes(raw).decode("ascii")


def set_role_password(db: Any, role: str, password: str, *, create: bool = False) -> None:
    from psycopg import sql

    verb = (
        "CREATE ROLE {} WITH LOGIN CREATEDB PASSWORD {}"
        if create
        else (
            "ALTER ROLE {} WITH PASSWORD {}"
            if role == SUPERUSER
            else "ALTER ROLE {} WITH LOGIN CREATEDB PASSWORD {}"
        )
    )
    statement = sql.SQL(verb).format(
        sql.Identifier(role), sql.Literal(scram_verifier(db, password, role))
    )
    error = _execute(db, statement)
    if error:
        raise NativePgError(f"Не вдалося змінити роль {role}: {error}")


# --------------------------------------------------------------------------- settings from .env


@dataclass(frozen=True)
class Native:
    port: int
    superuser_password: str = field(repr=False)
    app: Conn
    test: Conn

    def superuser(self, database: str = "postgres") -> Conn:
        return Conn(HOST, self.port, SUPERUSER, database, self.superuser_password)

    def as_app(self, database: str) -> Conn:
        return Conn(HOST, self.port, APP_ROLE, database, self.app.password)


def native_settings(env: Mapping[str, str]) -> Native:
    missing = [key for key in NATIVE_KEYS if not env.get(key)]
    if missing:
        raise NativePgError("У .env немає " + ", ".join(missing) + "; спершу виконайте secrets.")
    port = port_value(env, K_PORT, DEFAULT_NATIVE_PORT)
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
    """listen_addresses + role `journal`; True when a restart is pending."""
    with db.cursor() as cur:
        cur.execute("SHOW listen_addresses")
        if str(cur.fetchone()[0]) != "localhost":
            cur.execute("ALTER SYSTEM SET listen_addresses = 'localhost'")
            cur.execute("SELECT pg_reload_conf()")
            say("listen_addresses = 'localhost' записано (ALTER SYSTEM).")
        else:
            say("listen_addresses уже 'localhost'.")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        exists = cur.fetchone() is not None
    set_role_password(db, APP_ROLE, native.app.password, create=not exists)
    say(f"Роль {APP_ROLE}: {'пароль оновлено' if exists else 'створено'}.")
    with db.cursor() as cur:
        cur.execute("SELECT pending_restart FROM pg_settings WHERE name = 'listen_addresses'")
        return bool(cur.fetchone()[0])


def _superuser_accepts(native: Native, password: str) -> bool:
    try:
        with connect(Conn(HOST, native.port, SUPERUSER, "postgres", password)):
            return True
    except NativePgError:
        return False


def cmd_configure(env_file: Path, restart: bool, rotate: bool = True) -> int:
    env = env_values(read_env_text(env_file))
    native = native_settings(env)
    recover_rotation(env_file, env, lambda pw: _superuser_accepts(native, pw))
    native = native_settings(env_values(read_env_text(env_file)))
    dev = load_dev()
    say(f"Служба «{SERVICE}»: {service_state(dev) or 'не знайдена'}.")
    with connect(native.superuser(), autocommit=True) as db:
        pending = _configure_server(db, native)
        for name in (APP_DB, TEST_DB):
            ensure_database(db, name, lambda n: connect(native.superuser(n)))
        if rotate:
            rotate_superuser(env_file, lambda pw: set_role_password(db, SUPERUSER, pw))
    set_autostart(dev)
    if pending and restart:
        restart_service(dev, native.port)
    elif pending:
        say(
            "Потрібен перезапуск служби, щоб застосувати listen_addresses: повторіть "
            "configure --restart у PowerShell від імені адміністратора."
        )
    return 0


def dump_database(url: str, compose_port: int, name: str, label: str) -> Path:
    """Verified pg_dump to backups/<name>.dump (pg_restore --list + full read)."""
    from app.services.backups import BackupFailure, PostgresTools
    from app.tools.migrate import MigrateError

    final = BACKUPS / f"{name}.dump"
    partial = final.with_name(final.name + ".partial")
    tools = PostgresTools(compose_port=compose_port)
    say(f"Роблю pg_dump ({label})…")
    try:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        tools.dump(url, partial)
        tools.verify_archive(partial)
        partial.replace(final)
    except (BackupFailure, MigrateError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise NativePgError(
            f"Резервна копія ({label}) не вдалася: {exc}. Нічого не змінено."
        ) from None
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
    say(f"--replace: перестворюю нативну базу {APP_DB}…")
    with connect(native.superuser(), autocommit=True) as db:
        drop_database(db, APP_DB)
        create_database(db, APP_DB, lambda n: connect(native.superuser(n)))


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
        summary = restore_error_summary(result.stderr.decode("utf-8", errors="replace"))
        raise NativePgError(f"pg_restore завершився з кодом {result.returncode}: {summary}")


def _ensure_test_db(native: Native) -> None:
    with connect(native.as_app("postgres"), autocommit=True) as db:
        if not database_exists(db, TEST_DB):
            create_database(db, TEST_DB, lambda n: connect(native.as_app(n)))
            say(f"Базу {TEST_DB} створено (тести самі створюють схему).")


def _model_tables() -> list[str]:
    from app.models import Base

    return sorted(Base.metadata.tables)


def _copy_plan(
    env: Mapping[str, str], native: Native, native_active_ok: bool, replace: bool
) -> tuple[str, bool]:
    """(source URL, native active?) or NativePgError before any side effect."""
    active = env.get(K_URL, "")
    native_active = bool(active) and is_native(conn_from_url(active), native.port)
    if native_active and not native_active_ok:
        raise NativePgError(
            "Застосунок уже працює з нативною базою (DATABASE_URL); copy перезаписав би новіші "
            "дані старою копією з Docker. Нічого не змінено. Лише якщо ви справді цього хочете: "
            "--i-know-native-is-active --replace (спершу буде перевірений pg_dump нативної бази)."
        )
    if native_active and not replace:
        raise NativePgError("Нативна база активна: потрібен також --replace. Нічого не змінено.")
    source_url = env.get(K_DOCKER_URL, "") if native_active else env.get(K_DOCKER_URL) or active
    if not source_url:
        raise NativePgError(f"У .env немає {K_DOCKER_URL if native_active else K_URL}.")
    if is_native(conn_from_url(source_url), native.port):
        raise NativePgError("Джерело копіювання вказує на нативний сервер; нічого не скопійовано.")
    return source_url, native_active


def cmd_copy(env_file: Path, replace: bool, native_active_ok: bool = False) -> int:
    env = env_values(read_env_text(env_file))
    native = native_settings(env)
    source_url, native_active = _copy_plan(env, native, native_active_ok, replace)
    compose_port = port_value(env, "POSTGRES_PORT", DOCKER_PORT)
    ensure_app_stopped(load_dev())
    COPY_MARKER.unlink(missing_ok=True)  # an older verified copy no longer counts
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if native_active:
        dump_database(
            env[K_NATIVE_URL], compose_port, f"pre-replace-native-{stamp}", "нативна база"
        )
    dump = dump_database(source_url, compose_port, f"pre-native-{stamp}", "Docker")
    _prepare_target(native, replace)
    _restore(native, dump)
    _ensure_test_db(native)
    tables = _model_tables()
    with connect(conn_from_url(source_url)) as src, connect(native.app) as dst:
        source = snapshot(src, tables)
        result = compare(source, snapshot(dst, tables))
    for line in format_comparison(result):
        print(line, flush=True)
    if not result.ok:
        say("РІЗНИЦЯ між Docker і нативною базою. НЕ перемикайтеся (switch); див. таблицю вище.")
        return 1
    write_marker(dump, fingerprint(source.counts, source.alembic))
    say("Копію перевірено: усі таблиці, контрольні суми й ревізія alembic збігаються.")
    return 0


def write_marker(dump: Path, source_fp: str) -> None:
    COPY_MARKER.parent.mkdir(parents=True, exist_ok=True)
    data = {"verified_at": datetime.now(UTC).isoformat(), "dump": str(dump), "source": source_fp}
    COPY_MARKER.write_text(json.dumps(data), encoding="utf-8")


def read_marker_fingerprint() -> str | None:
    try:
        data = json.loads(COPY_MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("source") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _check_copy_current(env: Mapping[str, str]) -> None:
    expected = read_marker_fingerprint()
    if expected is None:
        raise NativePgError(
            "Немає підтвердженої копії (команда copy). Нічого не змінено; "
            "--force перемикає без неї."
        )
    if source_fingerprint(env.get(K_DOCKER_URL) or env[K_URL]) != expected:
        raise NativePgError(
            "Дані в Docker змінилися після copy (кількість рядків або ревізія alembic). "
            "Нічого не змінено; виконайте copy --replace ще раз."
        )


def write_switched_env(env_file: Path, text: str, updates: Mapping[str, str], command: str) -> None:
    """Back up the old .env (`.env.bak-<UTC>`), write the new one, and say plainly what changed:
    a switch is never silent (owner bug 2026-11-20: a recalled `switch-back` went unnoticed)."""
    now = datetime.now(UTC)
    backup = backup_env_file(env_file, now.strftime("%Y%m%dT%H%M%SZ"))
    new_text = set_env(text, updates)
    write_env_text(env_file, new_text)
    env = env_values(new_text)
    target = describe_active(
        env.get(K_URL, ""),
        port_value(env, K_PORT, DEFAULT_NATIVE_PORT),
        port_value(env, "POSTGRES_PORT", DOCKER_PORT),
    )
    say(
        f"{now:%Y-%m-%d %H:%M:%S} UTC: {command} ЗМІНИВ {env_file.name}: база застосунку тепер "
        f"{target}, {K_MODE}={env.get(K_MODE, '')}. Попередня версія: {backup.name}"
    )


def cmd_switch(env_file: Path, force: bool) -> int:
    ensure_app_stopped(load_dev())
    text = read_env_text(env_file)
    updates = switch_updates(raw_env(text))
    if set(updates) == {K_MODE}:  # URLs already native: only DB_MODE=native is written
        write_switched_env(env_file, text, updates, "switch")
        say(f"{K_MODE}=native записано (адреси вже нативні). Запустіть start.bat.")
        return 0
    if not force:
        _check_copy_current(env_values(text))
    write_switched_env(env_file, text, updates, "switch")
    COPY_MARKER.unlink(missing_ok=True)  # one verified copy, one switch
    say(
        "Перемкнено на нативний PostgreSQL (DATABASE_URL, TEST_DATABASE_URL, DB_MODE=native). "
        "Docker-адреси збережено як DOCKER_DATABASE_URL / DOCKER_TEST_DATABASE_URL. "
        "Запустіть start.bat."
    )
    return 0


def cmd_switch_back(env_file: Path) -> int:
    ensure_app_stopped(load_dev())
    text = read_env_text(env_file)
    write_switched_env(env_file, text, switch_back_updates(raw_env(text)), "switch-back")
    say(
        "Повернено Docker PostgreSQL (DATABASE_URL, TEST_DATABASE_URL, DB_MODE=docker). "
        "Запустіть Docker Desktop, потім start.bat."
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


def resolved_mode(dev: Any, env: Mapping[str, str], native_port: int, docker_port: int) -> str:
    """The launcher's DB mode (dev.resolve_db_mode); host/port only, never the URL."""
    try:
        host, port = dev.parse_db_host_port(env.get(K_URL, ""))
    except ValueError:
        return "невідомий (DATABASE_URL не задано або некоректний)"
    try:
        mode = dev.resolve_db_mode(
            env.get(K_MODE), host, port, native_port=native_port, docker_port=docker_port
        )
    except ValueError:
        return f"некоректний {K_MODE} (має бути native або docker)"
    return f"{mode} ({host}:{port})"


def cmd_status(env_file: Path) -> int:
    env = env_values(read_env_text(env_file))
    native_port = port_value(env, K_PORT, DEFAULT_NATIVE_PORT)
    docker_port = port_value(env, "POSTGRES_PORT", DOCKER_PORT)
    dev = load_dev()
    say(f"Режим БД: {resolved_mode(dev, env, native_port, docker_port)}")
    mode_key = env.get(K_MODE, "").strip()
    say(f"{K_MODE} у .env: {mode_key or 'не задано (режим визначено з DATABASE_URL)'}")
    say(f"Активна БД застосунку: {describe_active(env.get(K_URL, ''), native_port, docker_port)}")
    say(f"Тестова БД: {describe_active(env.get(K_TEST, ''), native_port, docker_port)}")
    say(f"Служба «{SERVICE}»: {service_state(dev) or 'не знайдена'}")
    for label, port in (("Docker", docker_port), ("native", native_port)):
        reachable = "доступний" if dev.tcp_reachable(HOST, port) else "недоступний"
        say(f"{label} {HOST}:{port}: {reachable}")
    say(f"Підтверджена копія: {'так' if COPY_MARKER.is_file() else 'ні'}")
    if env.get(K_SUPER_NEW):
        say(f"УВАГА: у .env є {K_SUPER_NEW} (незавершена зміна пароля): виконайте configure.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Перехід на нативний PostgreSQL 16.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("secrets").add_argument("--force", action="store_true")
    sub.add_parser("install-command")
    configure = sub.add_parser("configure")
    configure.add_argument("--restart", action="store_true")
    configure.add_argument("--no-rotate", action="store_true")
    copy = sub.add_parser("copy")
    copy.add_argument("--replace", action="store_true")
    copy.add_argument("--i-know-native-is-active", action="store_true")
    sub.add_parser("switch").add_argument("--force", action="store_true")
    sub.add_parser("switch-back")
    sub.add_parser("status")
    return parser


def run(args: argparse.Namespace, env_file: Path) -> int:
    commands: dict[str, Callable[[], int]] = {
        "secrets": lambda: cmd_secrets(env_file, args.force),
        "install-command": cmd_install_command,
        "configure": lambda: cmd_configure(env_file, args.restart, not args.no_rotate),
        "copy": lambda: cmd_copy(env_file, args.replace, args.i_know_native_is_active),
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

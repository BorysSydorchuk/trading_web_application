"""Start the M5 calculator QA app: own local QA DB, synthetic fixture MT5, AI forced off.

Stdlib only. Never touches the dev DB `trading_journal`; never drops, resets or deletes a
database or rows. Steps:
  1. accept only `postgresql+psycopg://...@<localhost>/trading_journal_qa_m5` (no URL params),
  2. refuse when an app is already running (ports 8000/5173, a recorded launcher, an orphan
     worker): scripts/dev.py would stop it, and this script must not stop what it did not start,
  3. copy config/ unchanged to `<base>/config` (default `%TEMP%\\tj-qa-m5`; data/ and logs/
     stay there too) and check it loads,
  4. create the QA database if it is missing (CREATE DATABASE only, via `uv run`),
  5. run scripts/dev.py (it migrates through `app.tools.migrate`, which makes the
     pre-migration pg_dump backup for this non-_test DB) with MT5_SOURCE =
     backend/tests/fixtures/mt5/calculator_qa.json (SYNTHETIC values) and ANTHROPIC_API_KEY="".

Modes:
  (default)        API + worker + frontend on 8000/5173 (stop: Ctrl+C or stop.bat)
  --prepare-only   create + migrate the QA DB, then exit
  --api-only       create + migrate, then only the API on port 8010, NO worker (margin
                   requests stay pending: the "worker stopped" check). Stop: Ctrl+C.
See docs/reports/M5-live-check.md.
"""

# Only fixed commands (uv, python) are executed; no user input reaches a shell.
# ruff: noqa: S603, S608, RUF001
# S608: CREATE_DB_SCRIPT is fixed child code (identifier via psycopg.sql), not a query.
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

import qa_live_check as common
import qa_live_check_m4 as m4

ROOT = common.ROOT
BACKEND = common.BACKEND
CONFIG_SRC = ROOT / "config"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"
QA_DB_NAME = "trading_journal_qa_m5"
QA_DATABASE_URL = f"postgresql+psycopg://journal:journal@127.0.0.1:5432/{QA_DB_NAME}"
DEFAULT_BASE = Path(tempfile.gettempdir()) / "tj-qa-m5"
COPY_MARKER = ".tj-qa-m5-copy"
MARKER_TEXT = "scripts/qa_live_check_m5.py\n"
FIXTURE_REL = "backend/tests/fixtures/mt5/calculator_qa.json"
QA_LOGIN = 51234570  # login of the synthetic fixture account
APP_PORTS = (8000, 5173)
API_ONLY_PORT = 8010
CREATE_DB_TIMEOUT_S = 120
QaError = common.QaError
validate_config = common.validate_config
run_dev = common.run_dev

# Runs in the backend venv (psycopg). URL only from the environment, never argv/output.
CREATE_DB_SCRIPT = f"""
import os, sys
from urllib.parse import unquote, urlsplit
import psycopg
from psycopg import sql
NAME = {QA_DB_NAME!r}
parts = urlsplit(os.environ.get("DATABASE_URL", ""))
if (
    parts.scheme != "postgresql+psycopg"
    or parts.hostname not in ("localhost", "127.0.0.1", "::1")
    or parts.path != "/" + NAME
    or parts.query
    or parts.fragment
):
    print("[qa] refused: not the local QA database " + NAME, flush=True)
    sys.exit(2)
try:
    with psycopg.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        dbname="postgres",
        autocommit=True,
        connect_timeout=5,
    ) as conn:
        found = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (NAME,)
        ).fetchone()
        if found:
            print("[qa] QA database " + NAME + " exists, kept as is", flush=True)
            sys.exit(0)
        conn.execute(sql.SQL("CREATE DATABASE {{}}").format(sql.Identifier(NAME)))
        print("[qa] QA database " + NAME + " created (empty)", flush=True)
except psycopg.Error as exc:
    print("[qa] PostgreSQL error: " + type(exc).__name__, flush=True)
    sys.exit(1)
sys.exit(0)
"""


def check_qa_database(url: str) -> None:
    m4.check_local_database(url, QA_DB_NAME)


def qa_env(
    base: Path,
    config: Path,
    database_url: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    check_qa_database(database_url)
    extra = {"MT5_SOURCE": f"fixture:{FIXTURE_REL}", f"MT5_PASSWORD_{QA_LOGIN}": "qa"}
    return m4.isolated_env(base, config, database_url, extra, environ)


def shown_env(env: Mapping[str, str]) -> str:
    """QA variables for the console; never the DB URL or a password."""
    keys = ("MT5_SOURCE", "DATA_DIR", "LOG_DIR", "CONFIG_DIR")
    shown = ", ".join(f"{k}={env[k]}" for k in keys if k in env)
    return f"{shown}, ANTHROPIC_API_KEY={'(порожній)' if not env.get('ANTHROPIC_API_KEY') else '?'}"


def prepare_config(src: Path, dest: Path) -> None:
    m4.prepare_marked_config(src, dest, COPY_MARKER, MARKER_TEXT, "M5")


def load_dev() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tj_dev_for_qa_m5", DEV_SCRIPT)
    if spec is None or spec.loader is None:
        raise QaError("Не знайдено scripts/dev.py.")
    module = importlib.util.module_from_spec(spec)
    # dev.py defines dataclasses: they look their module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_nothing_running(ports: Sequence[int]) -> None:
    """Refuse if anything could be stopped by dev.py: we only stop what we started."""
    dev = load_dev()
    busy = dev.busy_ports(ports)
    if busy:
        raise QaError(
            "Порти зайняті: " + ", ".join(map(str, busy)) + ". Нічого не зупиняю; "
            "зупиніть застосунок самі (stop.bat) і запустіть знову."
        )
    if dev.alive_records(dev.read_run_file(dev.RUN_FILE)) or dev.find_orphan_workers():
        raise QaError("Застосунок або worker уже запущений. Нічого не зупиняю; зупиніть його самі.")


def ensure_database(env: Mapping[str, str]) -> None:
    """CREATE DATABASE trading_journal_qa_m5 if missing; never drops or resets anything."""
    uv = shutil.which("uv")
    if not uv:
        raise QaError("Не знайдено uv у PATH.")
    try:
        result = subprocess.run(
            [uv, "run", "--project", str(BACKEND), "python", "-c", CREATE_DB_SCRIPT],
            cwd=BACKEND,
            env=dict(env),
            timeout=CREATE_DB_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise QaError("Не вдалося перевірити/створити QA-базу.") from None
    if result.returncode != 0:
        raise QaError("Не вдалося перевірити/створити QA-базу " + QA_DB_NAME + ".")


def run_api(env: Mapping[str, str], port: int) -> int:
    """Only the API (no worker, no frontend) until Ctrl+C."""
    uv = shutil.which("uv")
    if not uv:
        raise QaError("Не знайдено uv у PATH.")
    cmd = [uv, "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, cwd=BACKEND, env=dict(env))
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M5: QA-база trading_journal_qa_m5, синтетичний fixture MT5, AI вимкнено."
    )
    parser.add_argument("--no-browser", action="store_true", help="не відкривати браузер")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare-only", action="store_true", help="лише створити й мігрувати")
    modes.add_argument(
        "--api-only", action="store_true", help=f"лише API на порту {API_ONLY_PORT}, без worker"
    )
    parser.add_argument("--database-url", default=QA_DATABASE_URL, help="URL QA-бази M5")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE, help="QA-папка поза репо")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    common._utf8_console()
    try:
        base = args.base_dir.expanduser().resolve()
        config = base / "config"
        env = qa_env(base, config, args.database_url)
        m4.check_base_dir(base)
        if not (ROOT / FIXTURE_REL).is_file():
            raise QaError("Не знайдено синтетичний fixture " + FIXTURE_REL + ".")
        if args.api_only:
            check_nothing_running([API_ONLY_PORT])
        elif not args.prepare_only:
            check_nothing_running(APP_PORTS)
        common.say(f"QA-база {QA_DB_NAME}; AI вимкнено; MT5 = синтетичний fixture.")
        prepare_config(CONFIG_SRC, config)
        validate_config(env)
        common.say("Середовище: " + shown_env(env))
        ensure_database(env)
        if args.prepare_only:
            return run_dev(env, ["--ensure-db"])
        if args.api_only:
            code = run_dev(env, ["--ensure-db"])
            return code if code else run_api(env, API_ONLY_PORT)
        return run_dev(env, ["--no-browser"] if args.no_browser else [])
    except QaError as exc:
        # QaError texts here are fixed and never contain the URL.
        common.say(f"Помилка: {exc}")
        return 1
    except (OSError, UnicodeError):
        # Never echo exception text: OS/URL errors may contain connection secrets.
        common.say("Помилка: запуск QA відхилено. Перевірте QA-базу, шлях і позначку config/.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

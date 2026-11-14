"""Start the M6 digest/dashboard QA app NEXT TO the normal app: own DB, own ports, AI off.

Stdlib only. Never touches the dev DB `trading_journal`, `_test` DBs or older QA DBs; never
drops, resets or deletes a database or rows; never stops a process it did not start (the
normal app on 8000/5173 keeps running). Steps:
  1. accept only `postgresql+psycopg://...@<localhost>/trading_journal_qa_m6` (no URL params),
  2. (run mode) refuse when the QA ports 8020/5183 are busy,
  3. copy config/ unchanged to `<base>/config` (default `%TEMP%\\tj-qa-m6`; data/, logs/,
     the clock file and the QA run file stay there too) and check it loads,
  4. create the QA database if it is missing (CREATE DATABASE only, via `uv run`),
  5. migrate through `scripts/dev.py --ensure-db` (`app.tools.migrate`: pre-migration pg_dump
     for this non-_test DB); dev.py is never started in another mode (it would stop the
     normal app),
  6. --seed: sync the SYNTHETIC fixture backend/tests/fixtures/mt5/digest_qa.json into the
     empty QA DB with the real sync code (tests.fixtures.mt5.digest_qa_seed),
  7. run mode: API (no worker, MT5 never used) on 127.0.0.1:8020 with the clock pinned to
     `<base>/clock.txt` (read on every request, change it with --set-now), Vite on 5183
     proxying to 8020; then the fixture's bias notes / journal values / archive go through
     the HTTP API once. ANTHROPIC_API_KEY="" everywhere.

Modes:
  --prepare-only     create + migrate, then exit
  --seed             create + migrate + sync the fixture into an empty QA DB, then exit
  (default)          create + migrate + start API/UI with the pinned clock (--now, default the
                     fixture's qa_now) until Ctrl+C or --stop
  --set-now ISO      only rewrite the pinned clock of a running QA app
  --stop             stop the processes recorded by this launcher (verified PID + start time)
See docs/reports/M6-live-check.md.
"""

# Only fixed commands (uv, npm, python) are executed; no user input reaches a shell.
# ruff: noqa: S603, S608, RUF001
# S608: CREATE_DB_SCRIPT is fixed child code (identifier via psycopg.sql), not a query.
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import qa_live_check as common
import qa_live_check_m4 as m4

ROOT = common.ROOT
BACKEND = common.BACKEND
FRONTEND = ROOT / "frontend"
CONFIG_SRC = ROOT / "config"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"
QA_DB_NAME = "trading_journal_qa_m6"
QA_DATABASE_URL = f"postgresql+psycopg://journal:journal@127.0.0.1:5432/{QA_DB_NAME}"
DEFAULT_BASE = Path(tempfile.gettempdir()) / "tj-qa-m6"
COPY_MARKER = ".tj-qa-m6-copy"
MARKER_TEXT = "scripts/qa_live_check_m6.py\n"
FIXTURE_REL = "backend/tests/fixtures/mt5/digest_qa.json"
API_PORT = 8020
WEB_PORT = 5183
NORMAL_APP_PORTS = (8000, 5173)  # Borys's app: never used, never stopped
API_BASE = f"http://127.0.0.1:{API_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}/"
CLOCK_FILE = "clock.txt"
RUN_FILE = "qa-m6-run.json"
CREATE_DB_TIMEOUT_S = 120
SEED_TIMEOUT_S = 600
READY_TIMEOUT_S = 90.0
HTTP_TIMEOUT_S = 10.0
QaError = common.QaError
validate_config = common.validate_config
run_dev = common.run_dev

type Http = Callable[[str, str, Any], tuple[int, Any]]

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

# The QA API: the normal app object with "now" read from the clock file on every request.
API_SCRIPT = """
import os, sys
from datetime import UTC, datetime
from pathlib import Path
import uvicorn
from app.api import sync_status
from app.clock import utc_now
from app.main import app
CLOCK = Path(os.environ["TJ_QA_CLOCK_FILE"])
def pinned_now() -> datetime:
    text = CLOCK.read_text(encoding="utf-8").strip().replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(UTC)
app.dependency_overrides[utc_now] = pinned_now
app.dependency_overrides[sync_status.utc_now] = pinned_now
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="info")
"""

SEED_MODULE = "tests.fixtures.mt5.digest_qa_seed"


def check_qa_database(url: str) -> None:
    m4.check_local_database(url, QA_DB_NAME)


def qa_env(
    base: Path,
    config: Path,
    database_url: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    check_qa_database(database_url)
    extra = {
        # No worker runs; any MT5 read would fail on this non-format-1 file, never go real.
        "MT5_SOURCE": f"fixture:{FIXTURE_REL}",
        "TJ_API_PORT": str(API_PORT),
        "TJ_WEB_PORT": str(WEB_PORT),
        "API_PORT": str(API_PORT),
        "FRONTEND_PORT": str(WEB_PORT),
        "TJ_QA_CLOCK_FILE": str(base / CLOCK_FILE),
    }
    return m4.isolated_env(base, config, database_url, extra, environ)


def shown_env(env: Mapping[str, str]) -> str:
    """QA variables for the console; never the DB URL or a password."""
    keys = ("MT5_SOURCE", "DATA_DIR", "LOG_DIR", "CONFIG_DIR", "TJ_API_PORT", "TJ_WEB_PORT")
    shown = ", ".join(f"{k}={env[k]}" for k in keys if k in env)
    return f"{shown}, ANTHROPIC_API_KEY={'(порожній)' if not env.get('ANTHROPIC_API_KEY') else '?'}"


def prepare_config(src: Path, dest: Path) -> None:
    m4.prepare_marked_config(src, dest, COPY_MARKER, MARKER_TEXT, "M6")


def load_fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((ROOT / FIXTURE_REL).read_text(encoding="utf-8"))
    if "SYNTHETIC" not in data.get("description", ""):
        raise QaError("Fixture " + FIXTURE_REL + " не позначено як SYNTHETIC.")
    return data


def load_dev() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tj_dev_for_qa_m6", DEV_SCRIPT)
    if spec is None or spec.loader is None:
        raise QaError("Не знайдено scripts/dev.py.")
    module = importlib.util.module_from_spec(spec)
    # dev.py defines dataclasses: they look their module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_ports_free(ports: Sequence[int]) -> None:
    """Refuse the normal app's ports outright and any busy QA port; nothing is stopped."""
    normal = [p for p in ports if p in NORMAL_APP_PORTS]
    if normal:
        raise QaError(
            "Порти звичайного застосунку заборонені для QA: " + ", ".join(map(str, normal))
        )
    dev = load_dev()
    busy = [p for p in ports if dev.port_in_use(p)]
    if busy:
        raise QaError(
            "QA-порти зайняті: " + ", ".join(map(str, busy)) + ". Нічого не зупиняю; "
            "зупиніть попередній QA-запуск (--stop) і спробуйте знову."
        )


def write_clock(base: Path, value: str) -> str:
    """Store an aware ISO instant as UTC ``...Z`` in ``<base>/clock.txt``; returns it."""
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise QaError(
            "--now: потрібен ISO-час із часовим поясом, напр. 2026-11-13T15:00:00Z."
        ) from None
    if moment.tzinfo is None or "T" not in value:
        raise QaError("--now: потрібен ISO-час із часовим поясом, напр. 2026-11-13T15:00:00Z.")
    text = moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    base.mkdir(parents=True, exist_ok=True)
    (base / CLOCK_FILE).write_text(text + "\n", encoding="utf-8")
    return text


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise QaError("Не знайдено uv у PATH.")
    return uv


def ensure_database(env: Mapping[str, str]) -> None:
    """CREATE DATABASE trading_journal_qa_m6 if missing; never drops or resets anything."""
    try:
        result = subprocess.run(
            [_uv(), "run", "--project", str(BACKEND), "python", "-c", CREATE_DB_SCRIPT],
            cwd=BACKEND,
            env=dict(env),
            timeout=CREATE_DB_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise QaError("Не вдалося перевірити/створити QA-базу.") from None
    if result.returncode != 0:
        raise QaError("Не вдалося перевірити/створити QA-базу " + QA_DB_NAME + ".")


def run_seed(env: Mapping[str, str]) -> int:
    """Sync the SYNTHETIC fixture into the empty QA DB (the child refuses anything else)."""
    try:
        result = subprocess.run(
            [_uv(), "run", "python", "-m", SEED_MODULE],
            cwd=BACKEND,
            env=dict(env),
            timeout=SEED_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise QaError("Не вдалося запустити заповнення QA-бази.") from None
    return result.returncode


# --------------------------------------------------------------------------- HTTP seeding


def http_json(method: str, path: str, body: Any = None) -> tuple[int, Any]:
    """One request to the QA API only (fixed host and port)."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - fixed local http URL
        API_BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310
            raw = resp.read()
            return int(resp.status), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return int(exc.code), json.loads(raw) if raw else None


def _expect(status: int, wanted: int, what: str) -> None:
    if status != wanted:
        raise QaError(f"API-заповнення: {what} повернуло {status}, очікувано {wanted}.")


def _trade_ids(http: Http) -> dict[int, int]:
    status, page = http("GET", "/api/trades?limit=500", None)
    _expect(status, 200, "GET /api/trades")
    return {int(row["position_id"]): int(row["id"]) for row in page["items"]}


def _seed_bias(http: Http, notes: Sequence[Mapping[str, Any]]) -> None:
    for note in notes:
        entries = [{"symbol": e["symbol"], "direction": e["direction"]} for e in note["entries"]]
        body = {"kind": note["kind"], "period_date": note["period_date"], "entries": entries}
        status, created = http("POST", "/api/bias/notes", body)
        _expect(status, 201, "POST /api/bias/notes")
        by_symbol = {e["symbol"]: e["id"] for e in created["entries"]}
        for entry in note["entries"]:
            if entry["was_correct"] is None:
                continue
            path = f"/api/bias/entries/{by_symbol[entry['symbol']]}/result"
            status, _ = http("PATCH", path, {"was_correct": entry["was_correct"]})
            _expect(status, 200, "PATCH bias result")


def seed_api(http: Http, data: Mapping[str, Any]) -> bool:
    """Bias notes, draft journals and the archive, once (skipped when notes exist)."""
    status, notes = http("GET", "/api/bias/notes", None)
    _expect(status, 200, "GET /api/bias/notes")
    if notes["items"]:
        return False
    status, accounts = http("GET", "/api/accounts", None)
    _expect(status, 200, "GET /api/accounts")
    if not accounts["items"]:
        raise QaError("QA-база порожня: спершу запустіть --seed.")
    seed = data["api_seed"]
    _seed_bias(http, seed["bias_notes"])
    ids = _trade_ids(http)
    pids = {t["label"]: int(t["position_id"]) for t in data["trades"]}
    for item in seed["journal"]:
        body = {
            "fields": item["fields"],
            "chart_links": [],
            "raw_text": None,
            "ai_filled_fields": [],
            "complete": False,
        }
        status, _ = http("PUT", f"/api/trades/{ids[pids[item['label']]]}/journal", body)
        _expect(status, 200, "PUT journal")
    by_login = {int(a["login"]): int(a["id"]) for a in accounts["items"]}
    for account in data["accounts"]:
        if account["archive"]:
            status, _ = http("DELETE", f"/api/accounts/{by_login[int(account['login'])]}", None)
            _expect(status, 204, "DELETE /api/accounts (archive)")
    return True


# --------------------------------------------------------------------------- processes


def _start(cmd: Sequence[str], cwd: Path, env: Mapping[str, str]) -> subprocess.Popen[bytes]:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    # The child keeps its own copy of the handle; ours is closed right after the start.
    with (Path(env["LOG_DIR"]) / f"qa-m6-{Path(cwd).name}.out").open("ab") as log:
        return subprocess.Popen(
            list(cmd), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, creationflags=flags,
        )  # fmt: skip


def write_run_file(path: Path, records: Sequence[Any]) -> None:
    """dev.py's run-file format (so dev.read_run_file / alive_records verify it), QA ports."""
    dev = load_dev()
    data = {
        "version": dev.RUN_FILE_VERSION,
        "root": str(ROOT),
        "started_at": datetime.now(UTC).isoformat(),
        "ports": [API_PORT, WEB_PORT],
        "processes": [
            {"role": r.role, "pid": r.pid, "create_time": r.create_time, "cmdline": r.cmdline}
            for r in records
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _wait_ready(procs: Sequence[subprocess.Popen[bytes]]) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    api_ok = web_ok = False
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in procs):
            raise QaError(
                "API або Vite QA завершився під час старту; див. <base>/logs/qa-m6-*.out."
            )
        api_ok = api_ok or _get_ok(API_BASE + "/api/health")
        web_ok = web_ok or _get_ok(WEB_URL)
        if api_ok and web_ok:
            return
        time.sleep(0.5)
    raise QaError("QA-застосунок не відповів за 90 с; див. <base>/logs/qa-m6-*.out.")


def _get_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 - fixed local URL
            return int(resp.status) == 200
    except (urllib.error.URLError, OSError):
        return False


def start_servers(env: Mapping[str, str], base: Path) -> int:
    """API (pinned clock) + Vite on the QA ports until Ctrl+C or --stop; then stop them."""
    dev = load_dev()
    npm = shutil.which("npm")
    if not npm:
        raise QaError("Не знайдено npm у PATH.")
    Path(env["LOG_DIR"]).mkdir(parents=True, exist_ok=True)
    children = (
        ("api", [_uv(), "run", "python", "-c", API_SCRIPT, str(API_PORT)], BACKEND),
        ("web", [npm, "run", "dev"], FRONTEND),
    )
    procs: list[subprocess.Popen[bytes]] = []
    records = [dev.make_record("launcher", os.getpid())]
    try:
        for role, cmd, cwd in children:
            # Recorded right after each start: --stop finds a lone API if the UI fails.
            proc = _start(cmd, cwd, env)
            procs.append(proc)
            records.append(dev.make_record(role, proc.pid))
            write_run_file(base / RUN_FILE, [r for r in records if r is not None])
        _wait_ready(procs)
        if seed_api(http_json, load_fixture()):
            common.say("Біас-нотатки, чернетки журналу й архів рахунку C додано через API.")
        common.say(f"Готово: {WEB_URL} (API {API_BASE}). Зупинка: Ctrl+C або --stop.")
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for proc in procs:
            if proc.poll() is None:
                dev.kill_process_tree(proc.pid)
        (base / RUN_FILE).unlink(missing_ok=True)


def stop_recorded(base: Path) -> int:
    """Stop only the processes in <base>/qa-m6-run.json that are provably still ours."""
    dev = load_dev()
    alive = dev.alive_records(dev.read_run_file(base / RUN_FILE))
    for record, _info in alive:
        dev.kill_process_tree(record.pid)
    common.say(f"Зупинено QA-процесів: {len(alive)}.")
    return 0


# --------------------------------------------------------------------------- main


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M6: QA-база trading_journal_qa_m6, власні порти 8020/5183, AI вимкнено."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare-only", action="store_true", help="лише створити й мігрувати")
    modes.add_argument("--seed", action="store_true", help="мігрувати й заповнити з fixture")
    modes.add_argument("--set-now", metavar="ISO", help="лише змінити закріплений час QA-API")
    modes.add_argument("--stop", action="store_true", help="зупинити запущений QA-застосунок")
    parser.add_argument("--now", metavar="ISO", help="закріплений час (типово qa_now з fixture)")
    parser.add_argument("--database-url", default=QA_DATABASE_URL, help="URL QA-бази M6")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE, help="QA-папка поза репо")
    return parser.parse_args(argv)


def _prepare(env: Mapping[str, str], config: Path) -> None:
    prepare_config(CONFIG_SRC, config)
    validate_config(env)
    common.say("Середовище: " + shown_env(env))
    ensure_database(env)
    code = run_dev(env, ["--ensure-db"])
    if code:
        raise QaError("Міграції QA-бази не застосовано (див. вивід вище).")


def _run(args: argparse.Namespace, base: Path) -> int:
    config = base / "config"
    env = qa_env(base, config, args.database_url)
    m4.check_base_dir(base)
    if args.stop:
        return stop_recorded(base)
    if args.set_now:
        common.say("Закріплений час: " + write_clock(base, args.set_now))
        return 0
    if not (ROOT / FIXTURE_REL).is_file():
        raise QaError("Не знайдено синтетичний fixture " + FIXTURE_REL + ".")
    run_mode = not (args.prepare_only or args.seed)
    if run_mode:
        check_ports_free([API_PORT, WEB_PORT])
    common.say(f"QA-база {QA_DB_NAME}; AI вимкнено; MT5 не використовується (SYNTHETIC fixture).")
    _prepare(env, config)
    if args.prepare_only:
        return 0
    if args.seed:
        code = run_seed(env)
        if code:
            raise QaError("Заповнення QA-бази відхилено або не вдалося (див. [seed] вище).")
        return 0
    now = write_clock(base, args.now or str(load_fixture()["qa_now"]))
    common.say("Закріплений час: " + now)
    return start_servers(env, base)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    common._utf8_console()
    try:
        return _run(args, args.base_dir.expanduser().resolve())
    except QaError as exc:
        # QaError texts here are fixed and never contain the URL.
        common.say(f"Помилка: {exc}")
        return 1
    except (OSError, UnicodeError, ValueError, KeyError):
        # Never echo exception text: OS/URL errors may contain connection secrets.
        common.say("Помилка: запуск QA відхилено. Перевірте QA-базу, шлях і позначку config/.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

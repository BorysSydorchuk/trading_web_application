r"""Opt-in synthetic benchmark. Never accepts an existing application/QA DB as target.

Repo-root PowerShell: uv run --project backend python -m app.tools.performance
No performance thresholds run in pytest; failures remain explicit in JSON evidence.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import httpx
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, get_settings
from app.tools.performance_data import seed

TARGET = re.compile(r"tj_m705_\d{14}_[a-f0-9]{6}_test")


def validate_target(url: str) -> None:
    parsed = make_url(url)
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or not TARGET.fullmatch(parsed.database or "")
        or parsed.query
    ):
        raise ValueError("refused: not a generated local synthetic performance target")


def summarize(samples: list[float]) -> dict[str, Any]:
    if not samples:
        raise ValueError("No benchmark samples")
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3),
        "max_ms": round(max(samples), 3),
        "raw_ms": samples,
    }


def threshold_summary(samples: list[float], target: float) -> dict[str, Any]:
    return {
        **summarize(samples),
        "target_ms": target,
        "breaches": sum(value >= target for value in samples),
    }


def load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "tj_performance_dev", REPO_ROOT / "scripts/dev.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Launcher unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def create_dataset(runtime: Path) -> tuple[str, dict[str, Any]]:
    from app.config_files import reload_config
    from app.tools.migrate import alembic_config

    base = get_settings().test_database_url
    if not base:
        raise ValueError("TEST_DATABASE_URL required")
    parsed = make_url(base)
    if parsed.host not in {"127.0.0.1", "localhost"} or parsed.database != "trading_journal_test":
        raise ValueError("refused: expected local test database as creation connection")
    name = "tj_m705_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "_" + uuid4().hex[:6] + "_test"
    url = parsed.set(database=name).render_as_string(hide_password=False)
    validate_target(url)
    engine = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            if conn.scalar(text("SELECT current_database()")) != parsed.database:
                raise ValueError("creation connection identity mismatch")
            if conn.scalar(
                text("SELECT count(*) FROM pg_database WHERE datname=:name"), {"name": name}
            ):
                raise ValueError("refused: existing database")
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()
    shutil.copytree(REPO_ROOT / "config", runtime / "config")
    os.environ.update(
        DATABASE_URL=url,
        TEST_DATABASE_URL=url,
        CONFIG_DIR=str(runtime / "config"),
        DATA_DIR=str(runtime / "data"),
        LOG_DIR=str(runtime / "logs"),
        BACKUP_DIR=str(runtime / "backups"),
        ANTHROPIC_API_KEY="",
        MT5_SOURCE="fixture:" + str(REPO_ROOT / "backend/tests/fixtures/mt5/basic_week.json"),
    )
    get_settings.cache_clear()
    reload_config()
    command.upgrade(alembic_config(url), "head")  # New empty synthetic DB only.
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            manifest = seed(db)
    finally:
        engine.dispose()
    return name, manifest


def browser_measure(
    port: int, origin: str, repetitions: int, *, home_only: bool = False
) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 - fixed local script and generated ports
        [shutil.which("node") or "node", str(REPO_ROOT / "scripts/performance_browser.mjs")],
        input=json.dumps(
            {"debugPort": port, "origin": origin, "repetitions": repetitions, "homeOnly": home_only}
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=max(90, repetitions * 80),
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Browser benchmark failed: " + result.stderr[-1500:])
    answer: dict[str, Any] = json.loads(result.stdout)
    return answer


def api_measure(origin: str, repetitions: int) -> dict[str, Any]:
    entries: list[tuple[str, str, dict[str, Any] | None]] = [
        ("health", "/health", None),
        ("dashboard", "/dashboard", None),
        ("bias_status", "/bias/status", None),
        ("inbox", "/inbox/counts", None),
        ("sync", "/sync/status", None),
        ("accounts", "/accounts", None),
        ("journal_fields", "/journal-fields", None),
        ("trade_symbols", "/trades/symbols", None),
        ("journal_50", "/trades?limit=50&offset=0&sort=close_time&order=desc", None),
        ("journal_200", "/trades?limit=200&offset=0&sort=close_time&order=desc", None),
        ("weekly_list", "/digests?kind=weekly", None),
        ("monthly_list", "/digests?kind=monthly", None),
        ("digest_suggestion", "/digests/suggestion", None),
        ("weekly_detail", "/digests/by-period?kind=weekly&date=2026-11-09", None),
        ("symbol_specs", "/accounts/1/symbol-specs", None),
        (
            "calculator",
            "/calculator/calculate",
            {
                "account_id": 1,
                "symbol": "EURUSD",
                "direction": "buy",
                "entry": "1.10000",
                "sl_price": "1.09900",
                "risk_percent": "1",
            },
        ),
        ("generate_weekly", "/digests", {"kind": "weekly", "date": "2026-11-09"}),
    ]
    output = {}
    with httpx.Client(base_url=origin + "/api", timeout=30, trust_env=False) as client:
        for label, path, body in entries:
            samples = []
            for index in range(repetitions + 1):
                began = time.perf_counter()
                response = client.get(path) if body is None else client.post(path, json=body)
                response.raise_for_status()
                response.json()  # Include full response transfer + JSON decoding.
                elapsed = (time.perf_counter() - began) * 1000
                if index:
                    samples.append(elapsed)
            output[label] = {
                **threshold_summary(samples, 300),
                "method": "GET" if body is None else "POST",
                "path": path,
            }
    return output


def environment() -> dict[str, Any]:
    cpu = platform.processor()
    ram_gib: float | None = None
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            cpu = str(winreg.QueryValueEx(key, "ProcessorNameString")[0])
        import ctypes

        memory = ctypes.create_string_buffer(64)
        struct.pack_into("I", memory, 0, 64)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(memory):
            ram_gib = round(struct.unpack_from("Q", memory, 8)[0] / 1024**3, 2)
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "ram_gib": ram_gib,
        "node": subprocess.check_output(  # noqa: S603 - resolved executable, fixed version argument
            [shutil.which("node") or "node", "--version"], text=True, encoding="utf-8"
        ).strip(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("fastapi", "sqlalchemy", "psycopg", "uvicorn")
        },
    }


def execute(args: argparse.Namespace) -> Path:
    runtime = Path(tempfile.mkdtemp(prefix="tj-m705-"))
    name, dataset = create_dataset(runtime)
    print("Synthetic benchmark target: " + name, flush=True)
    dev: Any = load_launcher()
    dev.RUN_FILE, dev.STOP_REQUEST_FILE = runtime / "run.json", runtime / "stop.json"
    api_port, web_port, debug_port = free_port(), free_port(), free_port()
    os.environ.update(API_PORT=str(api_port), TJ_API_PORT=str(api_port), TJ_WEB_PORT=str(web_port))
    dev.HEALTH_URL, dev.WEB_URL = (
        f"http://127.0.0.1:{api_port}/api/health",
        f"http://127.0.0.1:{web_port}/",
    )
    origin = dev.WEB_URL.rstrip("/")
    chrome = args.chrome or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    machine = environment()
    revision = subprocess.check_output(  # noqa: S603 - fixed local Git query
        [shutil.which("git") or "git", "rev-parse", "main"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()
    browser = dev.start_child(
        "benchmark-browser",
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={runtime / 'chrome'}",
            "about:blank",
        ],
        REPO_ROOT,
    )
    report: dict[str, Any] = {
        "phase": args.phase,
        "dataset": dataset,
        "environment": machine,
        "product_base_revision": revision,
        "database": name,
        "runtime_directory": str(runtime),
        "startup": [],
        "methodology": {
            "api": "serial loopback HTTP keepalive incl transfer+JSON; "
            "1 excluded priming request per endpoint",
            "browser": "fresh React state on each document navigation; warm browser asset cache; "
            "usable DOM and no pending API fetch, two animation frames",
            "percentile": "nearest-rank p95; no hardware thresholds asserted by unit tests",
            "warm_start": "prerequisite checks + real preflight + no-pending migration + "
            "API/fixture-worker/Vite readiness + usable Home; Chrome already running; "
            "PostgreSQL and dependency caches warm",
        },
    }
    try:
        deadline = time.monotonic() + 20
        while dev.http_get(f"http://127.0.0.1:{debug_port}/json/version") is None:
            if time.monotonic() > deadline:
                raise RuntimeError("Private Chrome did not start")
            time.sleep(0.1)
        # First startup has a new browser/cache/config origin: report it separately.
        # The measured warm set begins only after this explicit priming startup.
        for iteration in range(args.startup_repetitions + 1):
            run = dev.Run()
            try:
                began = time.perf_counter()
                dev.check_python()
                uv, npm = dev.find_uv(), dev.find_npm()
                # Warm mode must never install dependencies or recover an owner's DB.
                for stamp, manifests in (
                    (dev.BACKEND_STAMP, [dev.BACKEND / "uv.lock", dev.BACKEND / "pyproject.toml"]),
                    (
                        dev.FRONTEND_STAMP,
                        [dev.FRONTEND / "package-lock.json", dev.FRONTEND / "package.json"],
                    ),
                ):
                    if dev.needs_install(stamp, manifests):
                        raise RuntimeError(
                            "Install dependencies with make dev before warm benchmarking"
                        )
                dev.ensure_dependencies(uv, npm)
                prerequisites_ms = (time.perf_counter() - began) * 1000
                run.add(dev.start_child("web", [npm, "run", "dev"], REPO_ROOT / "frontend"))
                target = make_url(os.environ["DATABASE_URL"])
                if not dev.tcp_reachable(target.host, target.port or 5432):
                    raise RuntimeError(
                        "Synthetic database unavailable; automatic recovery disabled"
                    )
                dev.ensure_db({"DATABASE_URL": os.environ["DATABASE_URL"]})
                dev.run_step(
                    [*uv, "run", "python", "-m", "app.tools.startup_check"],
                    REPO_ROOT / "backend",
                    dev.MSG["preflight"],
                    120,
                )
                preflight_ms = (time.perf_counter() - began) * 1000
                dev.migrate(uv)
                migration_ms = (time.perf_counter() - began) * 1000
                run.add(
                    dev.start_child(
                        "api",
                        [
                            *uv,
                            "run",
                            "uvicorn",
                            "app.tools.performance_app:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(api_port),
                        ],
                        REPO_ROOT / "backend",
                    )
                )
                run.add(
                    dev.start_child(
                        "worker", [*uv, "run", "python", "-m", "app.worker"], REPO_ROOT / "backend"
                    )
                )
                dev.wait_ready(run)
                ready_ms = (time.perf_counter() - began) * 1000
                home = browser_measure(debug_port, origin, 1, home_only=True)
                usable_ms = (time.perf_counter() - began) * 1000
                row = {
                    "iteration": iteration,
                    "ready_ms": ready_ms,
                    "usable_ui_ms": usable_ms,
                    "browser": home,
                    "stages_ms": {
                        "prerequisites": prerequisites_ms,
                        "preflight": preflight_ms - prerequisites_ms,
                        "no_pending_migration": migration_ms - preflight_ms,
                        "children_ready": ready_ms - migration_ms,
                        "usable_ui": usable_ms - ready_ms,
                    },
                }
                if iteration == 0:
                    report["first_startup_cold_browser_assets"] = row
                else:
                    report["startup"].append(row)
                if iteration == args.startup_repetitions:
                    report["api"] = api_measure(f"http://127.0.0.1:{api_port}", args.repetitions)
                    report["browser"] = browser_measure(debug_port, origin, args.repetitions)
            finally:
                run.close()
        report["warm_startup"] = threshold_summary(
            [row["usable_ui_ms"] for row in report["startup"]], 10000
        )
        report["browser_summary"] = {
            path: threshold_summary([row["ms"] for row in rows], 300)
            for path, rows in report["browser"]["samples"].items()
        }
        report["spa_summary"] = {
            path: threshold_summary([row["ms"] for row in rows], 300)
            for path, rows in report["browser"].get("spa", {}).items()
        }
        report["failures"] = (
            [label for label, row in report["api"].items() if row["breaches"]]
            + [
                "browser:" + path
                for path, row in report["browser_summary"].items()
                if row["breaches"]
            ]
            + ["spa:" + path for path, row in report["spa_summary"].items() if row["breaches"]]
            + (["warm_startup"] if report["warm_startup"]["breaches"] else [])
        )
        output = REPO_ROOT / "logs" / f"m7-05-{args.phase}-{name}.json"
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Evidence: " + str(output), flush=True)
        print("Performance target failures: " + str(report["failures"]), flush=True)
        return output
    finally:
        dev.stop_all([browser])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("baseline", "diagnostic", "after"), default="baseline")
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--startup-repetitions", type=int, default=5)
    parser.add_argument("--chrome")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 100 or not 1 <= args.startup_repetitions <= 30:
        parser.error("page repetitions must be 1..100; startup repetitions 1..30")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        execute(args)
    except Exception as error:
        # No URL/settings/driver detail in output.
        print("Benchmark failed: " + type(error).__name__, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

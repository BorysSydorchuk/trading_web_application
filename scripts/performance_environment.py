"""Opt-in cold-container / fresh-install timings. Never stops an existing container.

Normal repo-root PowerShell: python scripts/performance_environment.py
Existing Docker daemon stays running. New stopped containers/volumes and temp installs
are preserved, not deleted. Dependency caches are warm; network-cold install is not claimed.
"""

# ruff: noqa: S603 - fixed commands, generated temporary directories/container names
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median_ms": statistics.median(values),
        "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1],
        "raw_ms": values,
    }


def container_sample() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker unavailable")
    image = subprocess.run(
        [docker, "image", "inspect", "postgres:16", "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    name = "tj_m705_cold_" + uuid4().hex
    env = dict(os.environ)
    env["POSTGRES_PASSWORD"] = uuid4().hex  # Only synthetic; value never enters argv/output.
    began = time.perf_counter()
    created = subprocess.run(
        [
            docker,
            "run",
            "-d",
            "--pull=never",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            "POSTGRES_USER=journal",
            "-e",
            "POSTGRES_DB=synthetic_performance",
            "-p",
            "127.0.0.1::5432",
            "--health-cmd",
            "pg_isready -U journal -d synthetic_performance",
            "--health-interval=1s",
            "--health-timeout=2s",
            "--health-retries=60",
            image,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    try:
        deadline = time.monotonic() + 90
        while True:
            inspected = json.loads(
                subprocess.run(
                    [docker, "inspect", name], capture_output=True, text=True, check=True
                ).stdout
            )[0]
            if inspected["Id"] != created:
                raise RuntimeError("Container identity mismatch")
            if inspected["State"].get("Health", {}).get("Status") == "healthy":
                return {
                    "container": name,
                    "image": image,
                    "ms": (time.perf_counter() - began) * 1000,
                    "condition": "new PGDATA/container, existing warm Docker daemon "
                    "and cached image",
                }
            if time.monotonic() > deadline:
                raise RuntimeError("Synthetic container readiness timeout")
            time.sleep(0.25)
    finally:
        # Exact new container ID only, never compose stop/down or an existing app's name.
        subprocess.run([docker, "stop", created], capture_output=True, timeout=30, check=True)


def installation_sample() -> dict[str, Any]:
    checkout = Path(tempfile.mkdtemp(prefix="tj-m705-install-"))
    if shutil.disk_usage(checkout).free < 3 * 1024**3:
        raise RuntimeError("At least 3 GiB free required for isolated install")
    files = subprocess.run(
        [shutil.which("git") or "git", "ls-files", "--", "backend", "frontend", "config"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    for name in files:
        relative = Path(name)
        if "secrets" in relative.parts or any(part.startswith(".env") for part in relative.parts):
            continue
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    env = dict(os.environ)
    env.update(ANTHROPIC_API_KEY="", RUN_WHISPER_TESTS="0")
    env.pop("VIRTUAL_ENV", None)
    commands = [
        (
            "uv_sync",
            [shutil.which("uv") or "uv", "sync", "--offline", "--frozen"],
            checkout / "backend",
        ),
        (
            "npm_ci",
            [shutil.which("npm") or "npm", "ci", "--offline", "--no-audit", "--no-fund"],
            checkout / "frontend",
        ),
        ("frontend_build", [shutil.which("npm") or "npm", "run", "build"], checkout / "frontend"),
    ]
    result: dict[str, Any] = {
        "directory": str(checkout),
        "condition": "new checkout, empty venv/node_modules; shared warm dependency "
        "caches; offline",
    }
    for label, argv, directory in commands:
        began = time.perf_counter()
        completed = subprocess.run(
            argv,
            cwd=directory,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=900,
            check=False,
        )
        result[label] = {
            "ms": (time.perf_counter() - began) * 1000,
            "exit_code": completed.returncode,
        }
        if completed.returncode:
            result["failed_stage"] = label
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10:
        parser.error("repetitions must be 1..10")
    results: dict[str, Any] = {
        "docker_engine_cold": "not measured: existing owner daemon must not be stopped",
        "network_cold_install": "not measured: offline caches used; "
        "this is not a download-speed benchmark",
    }
    try:
        results["cold_containers"] = [container_sample() for _ in range(args.repetitions)]
        results["fresh_installations"] = [installation_sample() for _ in range(args.repetitions)]
        results["cold_container_summary"] = summary([r["ms"] for r in results["cold_containers"]])
        results["installation_summary"] = {
            stage: summary([r[stage]["ms"] for r in results["fresh_installations"] if stage in r])
            for stage in ("uv_sync", "npm_ci", "frontend_build")
            if any(stage in r for r in results["fresh_installations"])
        }
    except Exception as error:
        results["failure"] = type(error).__name__  # No external stderr or credentials.
    output = (
        ROOT
        / "logs"
        / ("m7-05-environment-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    )
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(str(output), flush=True)
    return int(
        "failure" in results
        or any("failed_stage" in r for r in results.get("fresh_installations", []))
    )


if __name__ == "__main__":
    raise SystemExit(main())

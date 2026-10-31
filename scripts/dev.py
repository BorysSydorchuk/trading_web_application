"""Dev launcher for the Trading Journal app (used by `start.bat` and `make dev`).

Stdlib only, Python 3.12+. Steps:
  1. prerequisite checks (Python, Node/npm, uv),
  2. `.env` from `.env.example` if missing,
  3. `uv sync` / `npm install` when dependencies are missing or stale,
  4. PostgreSQL reachable (starts the Docker `db` service if needed) + `alembic upgrade head`,
  5. starts API, worker and Vite dev server with prefixed output,
  6. waits for http://127.0.0.1:8000/api/health and http://127.0.0.1:5173/, opens the browser.

Ctrl+C (or any child exiting) stops everything; on Windows whole process trees are killed.

Usage:
  python scripts/dev.py               start everything and open the browser
  python scripts/dev.py --no-browser  same, without opening the browser
  python scripts/dev.py --ensure-db   only make sure the DB is up and migrated, then exit
"""

# Only fixed commands (uv, npm, docker, taskkill) are executed; no user input reaches them.
# ruff: noqa: S603, S607

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# Fixed by frontend/vite.config.ts (strictPort + /api proxy target); keep in sync.
API_HOST = "127.0.0.1"
API_PORT = 8000
WEB_PORT = 5173
HEALTH_URL = f"http://{API_HOST}:{API_PORT}/api/health"
WEB_URL = f"http://{API_HOST}:{WEB_PORT}/"

READY_TIMEOUT_S = 60.0
DOCKER_START_TIMEOUT_S = 120.0
DB_TCP_TIMEOUT_S = 30.0
MIN_NODE = (20, 19)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

BACKEND_STAMP = BACKEND / ".venv" / ".dev-sync-stamp"
FRONTEND_STAMP = FRONTEND / "node_modules" / ".dev-install-stamp"

IS_WINDOWS = sys.platform == "win32"


class LauncherError(Exception):
    """A readable, expected failure: printed without a traceback, exit code 1."""


# --------------------------------------------------------------------------- output

_print_lock = threading.Lock()


def say(msg: str) -> None:
    with _print_lock:
        print(f"[dev] {msg}", flush=True)


# --------------------------------------------------------------------------- pure helpers


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a simple dotenv file: KEY=VALUE lines, `#` comments, optional quotes."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


DB_URL_ERROR = (
    "could not read host/port from DATABASE_URL; expected "
    "postgresql+psycopg://user:password@host:5432/db and URL-encode special characters "
    "(/ # ? @ :) in the password"
)


def parse_db_host_port(url: str) -> tuple[str, int]:
    """Host and port of a SQLAlchemy/libpq style URL (`postgresql+psycopg://u:p@h:5432/db`).

    Defaults: host `localhost`, port 5432. Raises ValueError with a fixed message (never
    containing parts of the URL, which may hold the password) for a malformed URL.
    """
    scheme, sep, rest = url.partition("://")
    if not sep or not scheme.startswith("postgres"):
        raise ValueError(DB_URL_ERROR)
    parts = urlsplit(url)
    # An unencoded / # ? in the password ends the netloc early: the '@' then sits in the
    # path/query/fragment and part of the password would be read as host or port.
    if "@" in rest and "@" not in parts.netloc:
        raise ValueError(DB_URL_ERROR)
    try:
        port = parts.port or 5432  # raises for a non-numeric or out-of-range port
    except ValueError:
        raise ValueError(DB_URL_ERROR) from None
    return parts.hostname or "localhost", port


def needs_install(stamp: Path, manifests: Sequence[Path]) -> bool:
    """True if `stamp` is missing or any existing manifest is newer than it."""
    if not stamp.exists():
        return True
    stamp_mtime = stamp.stat().st_mtime
    return any(m.exists() and m.stat().st_mtime > stamp_mtime for m in manifests)


def parse_node_version(text: str) -> tuple[int, int]:
    """`v22.12.0` -> (22, 12)."""
    parts = text.strip().lstrip("v").split(".")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def is_local_host(host: str) -> bool:
    return host.lower() in LOCAL_HOSTS


# --------------------------------------------------------------------------- environment


def load_env() -> dict[str, str]:
    """Values from `.env`, overridden by the process environment (same as pydantic-settings)."""
    values = parse_env_file(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.exists() else {}
    for key in {*values, "DATABASE_URL", "TEST_DATABASE_URL"}:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    if not ENV_EXAMPLE.exists():
        raise LauncherError(".env and .env.example are both missing; is this a full clone?")
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    say("Created .env from .env.example (edit it to change DB settings or add API keys).")


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # An activated foreign venv makes `uv run` warn; the backend has its own .venv.
    env.pop("VIRTUAL_ENV", None)
    return env


# --------------------------------------------------------------------------- prerequisites


def check_python() -> None:
    if sys.version_info < (3, 12):  # noqa: UP036 - the launcher may run on an old python
        raise LauncherError(
            f"Python 3.12+ is required, found {sys.version.split()[0]}. See README (Prerequisites)."
        )


def find_uv() -> list[str]:
    exe = shutil.which("uv")
    if exe:
        return [exe]
    fallback = [sys.executable, "-m", "uv"]
    try:
        ok = (
            subprocess.run(
                [*fallback, "--version"], capture_output=True, timeout=20, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if ok:
        return fallback
    raise LauncherError(
        "uv not found. Install it (PowerShell): "
        'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" '
        "then open a new terminal. See README."
    )


def find_npm() -> str:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise LauncherError(
            "Node.js/npm not found. Install Node LTS: winget install OpenJS.NodeJS.LTS "
            "then open a new terminal. See README."
        )
    try:
        out = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=20, check=True
        ).stdout
        version = parse_node_version(out)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise LauncherError(f"Could not run `node --version`: {exc}") from exc
    if version < MIN_NODE:
        raise LauncherError(
            f"Node {MIN_NODE[0]}.{MIN_NODE[1]}+ is required (Vite 8), found {out.strip()}. "
            "Install the current LTS: winget install OpenJS.NodeJS.LTS"
        )
    return npm


def run_step(cmd: Sequence[str], cwd: Path, what: str, timeout: float | None = None) -> None:
    """Run a blocking setup command with its output shown; readable error on failure."""
    say(f"{what}...")
    try:
        result = subprocess.run(list(cmd), cwd=cwd, env=child_env(), timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise LauncherError(f"{what} timed out after {timeout:.0f} s.") from exc
    except OSError as exc:
        raise LauncherError(f"{what} could not start: {exc}") from exc
    if result.returncode != 0:
        raise LauncherError(f"{what} failed (exit code {result.returncode}); see output above.")


def ensure_dependencies(uv: Sequence[str], npm: str) -> None:
    if needs_install(BACKEND_STAMP, [BACKEND / "uv.lock", BACKEND / "pyproject.toml"]):
        run_step([*uv, "sync"], BACKEND, "Installing backend dependencies (uv sync)", 900)
        BACKEND_STAMP.touch()
    if needs_install(FRONTEND_STAMP, [FRONTEND / "package-lock.json", FRONTEND / "package.json"]):
        run_step(
            [npm, "install", "--no-audit", "--no-fund"],
            FRONTEND,
            "Installing frontend dependencies (npm install)",
            900,
        )
        FRONTEND_STAMP.touch()


# --------------------------------------------------------------------------- database


def tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_tcp(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if tcp_reachable(host, port):
            return True
        time.sleep(0.5)
    return False


def docker_daemon_running(docker: str) -> bool:
    try:
        return (
            subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=30,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def try_start_docker_desktop(docker: str) -> bool:
    """Windows only: launch Docker Desktop and wait for the daemon. False if not possible."""
    if sys.platform != "win32":
        return False
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    exe = Path(program_files) / "Docker" / "Docker" / "Docker Desktop.exe"
    if not exe.exists():
        return False
    wait_s = f"{DOCKER_START_TIMEOUT_S:.0f}"
    say(f"Docker is not running; starting Docker Desktop (waiting up to {wait_s} s)...")
    try:
        subprocess.Popen(
            [str(exe)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError:
        return False
    deadline = time.monotonic() + DOCKER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if docker_daemon_running(docker):
            return True
        time.sleep(3)
    return False


def ensure_db(env: Mapping[str, str]) -> None:
    url = env.get("DATABASE_URL", "")
    if not url:
        raise LauncherError("DATABASE_URL is not set in .env (see .env.example).")
    try:
        host, port = parse_db_host_port(url)
    except ValueError:
        # Fixed text only: the URL (and so any exception text) may contain the password.
        raise LauncherError(f"Invalid DATABASE_URL: {DB_URL_ERROR}.") from None

    if tcp_reachable(host, port):
        say(f"PostgreSQL reachable at {host}:{port}.")
        return

    docker = shutil.which("docker")
    if not is_local_host(host) or not docker:
        hint = (
            "Install Docker Desktop, or install PostgreSQL 16 and set DATABASE_URL in .env."
            if not docker
            else "DATABASE_URL points to a remote host; make sure that server is running."
        )
        raise LauncherError(f"PostgreSQL is not reachable at {host}:{port}. {hint} See README.")

    if not docker_daemon_running(docker) and not try_start_docker_desktop(docker):
        raise LauncherError(
            f"PostgreSQL is not reachable at {host}:{port} and the Docker daemon is not running. "
            "Start Docker Desktop, wait until it says 'Engine running', then try again."
        )

    run_step(
        [docker, "compose", "up", "-d", "--wait", "db"],
        ROOT,
        "Starting PostgreSQL in Docker (docker compose up -d --wait db)",
        600,
    )
    if not wait_tcp(host, port, DB_TCP_TIMEOUT_S):
        raise LauncherError(
            f"Docker started the db service but {host}:{port} is still not reachable. "
            "Check POSTGRES_PORT and DATABASE_URL in .env, and `docker compose logs db`."
        )
    say(f"PostgreSQL reachable at {host}:{port}.")


def migrate(uv: Sequence[str]) -> None:
    run_step([*uv, "run", "alembic", "upgrade", "head"], BACKEND, "Applying DB migrations", 300)


# --------------------------------------------------------------------------- child processes


def port_in_use(port: int, host: str = API_HOST) -> bool:
    """True if something already listens on host:port (bind test, instant on Windows)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def check_ports() -> None:
    busy = [p for p in (API_PORT, WEB_PORT) if port_in_use(p)]
    if busy:
        ports = ", ".join(str(p) for p in busy)
        how = (
            "Find the process with `netstat -ano | findstr :<port>` and stop it "
            "(`taskkill /PID <pid> /F`)"
            if IS_WINDOWS
            else "Find the process with `lsof -i :<port>` and stop it"
        )
        raise LauncherError(
            f"Port(s) {ports} already in use (is the app already running in another window?). "
            f"{how}."
        )


@dataclass
class Child:
    name: str
    proc: subprocess.Popen[bytes]
    reader: threading.Thread = field(init=False)

    def __post_init__(self) -> None:
        self.reader = threading.Thread(target=self._pump, name=f"pump-{self.name}", daemon=True)
        self.reader.start()

    def _pump(self) -> None:
        stream: IO[bytes] | None = self.proc.stdout
        if stream is None:
            return
        prefix = f"[{self.name}] "
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            with _print_lock:
                print(prefix + line, flush=True)


def start_child(name: str, cmd: Sequence[str], cwd: Path) -> Child:
    # Own process group/session: console Ctrl+C reaches only the launcher, which then kills
    # each tree (also avoids cmd's "Terminate batch job (Y/N)?" prompt for npm.cmd).
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creationflags = 0
    try:
        proc = subprocess.Popen(
            list(cmd),
            cwd=cwd,
            env=child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=not IS_WINDOWS,
        )
    except OSError as exc:
        raise LauncherError(f"Could not start {name}: {exc}") from exc
    return Child(name, proc)


def _signal_group(pid: int, sig_name: str) -> None:
    """POSIX: signal a child's whole session/process group (no-op on Windows)."""
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, getattr(signal, sig_name))


def kill_tree(child: Child) -> None:
    proc = child.proc
    if IS_WINDOWS:
        # Kill the whole tree while the root still exists (uv/npm spawn python/node children).
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    else:
        _signal_group(proc.pid, "SIGTERM")
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _signal_group(proc.pid, "SIGKILL")
        proc.kill()
        proc.wait(timeout=5)


def stop_all(children: Sequence[Child]) -> None:
    if not children:
        return
    # A second Ctrl+C/Ctrl+Break must not abort cleanup and leave process trees alive.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    say("Stopping...")
    for child in reversed(children):
        try:
            kill_tree(child)
        except (OSError, subprocess.SubprocessError) as exc:
            say(f"Could not stop {child.name} (pid {child.proc.pid}): {exc}")
    for child in children:
        child.reader.join(timeout=2)
    say("All processes stopped.")


def check_children(children: Sequence[Child]) -> None:
    for child in children:
        code = child.proc.poll()
        if code is not None:
            raise LauncherError(
                f"{child.name} exited unexpectedly (exit code {code}); see its output above "
                "and logs/."
            )


def http_get(url: str, timeout: float = 2.0) -> tuple[int, bytes] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local http
            status: int = resp.status
            return status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError):
        return None


def wait_ready(children: Sequence[Child]) -> str:
    """Wait for the API health endpoint and the Vite page. Returns the health status."""
    deadline = time.monotonic() + READY_TIMEOUT_S
    health_status: str | None = None
    web_ok = False
    while time.monotonic() < deadline:
        check_children(children)
        if health_status is None:
            res = http_get(HEALTH_URL)
            if res is not None and res[0] == 200:
                try:
                    health_status = str(json.loads(res[1]).get("status", "unknown"))
                except (ValueError, AttributeError):
                    health_status = "unknown"
        if not web_ok:
            res = http_get(WEB_URL)
            web_ok = res is not None and res[0] == 200
        if health_status is not None and web_ok:
            return health_status
        time.sleep(0.25)
    missing = []
    if health_status is None:
        missing.append(f"API ({HEALTH_URL})")
    if not web_ok:
        missing.append(f"frontend ({WEB_URL})")
    raise LauncherError(
        f"Timed out after {READY_TIMEOUT_S:.0f} s waiting for {' and '.join(missing)}. "
        "See the output above and logs/."
    )


# --------------------------------------------------------------------------- main


def run_dev(open_browser: bool, started: float) -> int:
    uv = find_uv()
    npm = find_npm()
    ensure_env_file()
    ensure_dependencies(uv, npm)
    check_ports()

    children: list[Child] = []
    try:
        # The frontend does not need the DB: start it first so it boots while we migrate.
        children.append(start_child("web", [npm, "run", "dev"], FRONTEND))
        ensure_db(load_env())
        migrate(uv)
        check_children(children)
        children.append(
            start_child(
                "api",
                [
                    *uv,
                    "run",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    API_HOST,
                    "--port",
                    str(API_PORT),
                ],
                BACKEND,
            )
        )
        children.append(start_child("worker", [*uv, "run", "python", "-m", "app.worker"], BACKEND))

        health = wait_ready(children)
        elapsed = time.monotonic() - started
        say(f"Ready in {elapsed:.1f} s: {WEB_URL} (API health: {health})")
        if health != "ok":
            say("WARNING: API health is not 'ok' (database problem?); see logs/api.log.")
        if open_browser:
            webbrowser.open(WEB_URL)
        say("Press Ctrl+C to stop.")
        while True:
            check_children(children)
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        stop_all(children)


def run_ensure_db() -> int:
    uv = find_uv()
    ensure_env_file()
    ensure_db(load_env())
    migrate(uv)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description="Start the Trading Journal app for development.")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument(
        "--ensure-db",
        action="store_true",
        help="only make sure PostgreSQL is running and migrated, then exit",
    )
    args = parser.parse_args(argv)

    # Child output may contain non-ASCII (Ukrainian); never crash on a legacy console codepage.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    # Ctrl+Break (Windows) / SIGTERM (POSIX) stop cleanly like Ctrl+C, children included.
    def _interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _interrupt)
    else:
        signal.signal(signal.SIGTERM, _interrupt)

    try:
        check_python()
        if args.ensure_db:
            return run_ensure_db()
        return run_dev(open_browser=not args.no_browser, started=started)
    except LauncherError as exc:
        say(f"ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        say("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())

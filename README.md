# Trading Journal

A local, single-user trading journal for prop-firm accounts on MetaTrader 5. A background
worker reads closed trades from MT5 (read-only, it never places or changes orders), the app
computes risk, R multiple, session and rule violations, and you describe each trade by text or
voice; Claude fills the journal fields from your description. Bias notes, digests and a position
size calculator build on the same data. Everything runs on your own Windows machine: FastAPI +
PostgreSQL backend, a separate sync worker and a React UI (in Ukrainian) at http://127.0.0.1:5173.

## Prerequisites (Windows)

Install once, then **open a new terminal** so PATH changes apply.

| Tool | Install |
| --- | --- |
| Git | `winget install Git.Git` |
| Python 3.12 | `winget install Python.Python.3.12` (tick "Add python.exe to PATH" if you use the installer from python.org) |
| Node.js LTS (20.19+ / 22.12+) | `winget install OpenJS.NodeJS.LTS` |
| uv (Python package manager) | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Docker Desktop (default DB) | `winget install Docker.DockerDesktop` (or use native PostgreSQL 16, see below) |
| GNU make (only for `make ...` commands) | `winget install ezwinports.make` |

Check: `python --version` (3.12.x), `node --version`, `uv --version`, `docker --version`.

## Quick start

```bat
git clone <repo-url> trading-journal
cd trading-journal
.\start.bat
```

`.\start.bat` works in both PowerShell (the default Windows 11 terminal) and cmd. Or just
double-click `start.bat` in Explorer. On the first run it:

1. creates `.env` from `.env.example` (edit it later for API keys and MT5 passwords),
2. installs backend (`uv sync`) and frontend (`npm install`) dependencies (a few minutes once),
3. starts PostgreSQL in Docker if it is not reachable (Docker Desktop must be installed; if it
   is not running the launcher starts it and waits up to 60 s:
   `Docker Desktop не запущено — запускаю, чекаю до 60 с…`),
4. applies DB migrations,
5. starts the API (`[api]`), the worker (`[worker]`) and the UI dev server (`[web]`) in one
   window, waits until they respond and opens http://127.0.0.1:5173 in your browser.

**What you should see:** the dark UI with the sidebar (Головна, Потрібен опис, Журнал, Біас,
Дайджести, Калькулятор, Налаштування), empty pages, and a green status bar (backend and DB OK).
The console prints `Готово за N с: http://127.0.0.1:5173/ (стан API: ok)`; a warm start takes a
few seconds. Launcher messages (`[dev]`) are in Ukrainian.

Stop with **Ctrl+C** in that window (all processes are stopped). If cmd then asks
`Terminate batch job (Y/N)?`, answer `Y`; the app is already stopped. `.\start.bat --no-browser`
starts without opening the browser.

### Stopping and restarting

- **`.\stop.bat`** (or double-click it) stops a running app from any window and prints what it
  stopped, e.g. `Зупинено: api uv.exe (PID 1234).` and `Застосунок зупинено.` When nothing
  runs it prints `Застосунок не запущено, нічого зупиняти.` A launcher that is still running
  gets a stop request and shuts its processes down itself, so its window closes normally.
- **Automatic cleanup on start:** `start.bat` first stops a previous run of this app, for
  example when the launcher window was closed or killed from Task Manager and the API/UI were
  left running (`Знайдено попередній запуск застосунку: … Зупиняю його…`). You never need to
  hunt for PIDs.
- How it knows what is "ours": the launcher writes `logs/dev-run.json` with its own PID and
  every child PID, each with the process creation time and command line, and deletes it on a
  clean exit. A recorded PID is stopped only if creation time and command line still match
  (a reused PID is never touched). If the file is lost, the API, UI and worker of this checkout
  are still recognised by their command line (`backend\.venv`, `frontend\node_modules`).
- A port held by **another program** is never stopped; the launcher names it and exits:
  `Порт 8000 зайнятий іншою програмою: python.exe (PID 4321). …`

## Everyday commands

Run from the repo root (needs GNU make):

| Command | What it does |
| --- | --- |
| `make dev` | same as `start.bat` (`python scripts/dev.py`) |
| `make stop` | same as `stop.bat` (`python scripts/dev.py --stop`) |
| `make check` | lint (ruff, eslint), type check (mypy, tsc), tests (pytest); starts the DB if needed |
| `make migrate` | apply Alembic migrations (`alembic upgrade head`) |
| `make db-ensure` | start the DB if needed and migrate, then exit |
| `make install` | install backend and frontend dependencies |

Without make: `python scripts/dev.py [--no-browser | --ensure-db | --stop]`.

## Using native PostgreSQL instead of Docker

1. Install PostgreSQL 16 (`winget install PostgreSQL.PostgreSQL.16`) and remember the
   `postgres` password.
2. Create a user and two databases (psql as `postgres`):

   ```sql
   CREATE USER journal WITH PASSWORD 'journal';
   CREATE DATABASE trading_journal OWNER journal;
   CREATE DATABASE trading_journal_test OWNER journal;
   \c trading_journal_test
   ALTER SCHEMA public OWNER TO journal;  -- tests drop and recreate schema public
   ```

3. In `.env` set `DATABASE_URL` and `TEST_DATABASE_URL`, e.g.
   `DATABASE_URL=postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal` and
   `TEST_DATABASE_URL=postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal_test`.

If the database is reachable, the launcher never touches Docker.

## MT5 terminal setup

Coming in milestone M1 (one portable terminal per account, read-only investor password in `.env`).

## Logs

- `logs/api.log`, `logs/worker.log`: rotating log files (UTC timestamps). Errors shown in the
  UI are logged here with details.
- The `start.bat` window shows the live output of all processes, prefixed `[api]`, `[worker]`,
  `[web]`, `[dev]`.

## Project layout

```
backend/            FastAPI app (package app), worker (app/worker), Alembic migrations, tests
frontend/           React + TypeScript + Vite UI; all UI strings in src/i18n/uk.ts
config/             YAML config (journal fields, rules) from M1
docker/             Postgres init scripts (creates the test DB)
scripts/dev.py      launcher used by start.bat, stop.bat, make dev and make stop
docs/               PRD, roadmap, API contract, decisions, status, milestone reports
logs/, data/        runtime logs and data (gitignored)
docker-compose.yml  local PostgreSQL 16 (service db, port 5432)
```

## Troubleshooting

- **`Docker Desktop не запустився за 60 с`** (or `Docker Desktop не запущено, і запустити його
  автоматично не вдалося`): start Docker Desktop yourself, wait until it shows "Engine
  running", run `.\start.bat` again. First start downloads the `postgres:16` image.
- **`Порт 8000 зайнятий іншою програмою: <name> (PID <pid>)`**: some other program (not this
  app) uses the port. Close it or run `taskkill /PID <pid> /F`. A previous run of this app is
  stopped automatically and never causes this error; `.\stop.bat` stops it explicitly.
- **`PostgreSQL недоступний на 127.0.0.1:5432`** with native Postgres: check the service is
  running (`services.msc`, postgresql-x64-16) and `DATABASE_URL` in `.env`.
- **Port 5432 taken by a native Postgres** while you want Docker: set `POSTGRES_PORT=5433` and
  use port 5433 in both URLs in `.env`.
- **`uv`, `node` or `python` not found** right after installing: open a new terminal.
- **Status bar red/yellow**: see `logs/api.log` (DB down or wrong credentials).

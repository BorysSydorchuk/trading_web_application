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
4. checks YAML/settings, writable data/log/backup directories, SQL database identity and
   PostgreSQL backup tools, then applies migrations only after a verified pre-migration dump,
5. starts the API (`[api]`), the worker (`[worker]`) and the UI dev server (`[web]`) in one
   window, waits for healthy API/DB, the worker's scheduler acknowledgement and the Vite
   page, then opens http://127.0.0.1:5173 in your browser.

Startup requires Python **3.12.x**, Node **20.19.x or >=22.12**, executable npm and uv.
Backup preflight checks `pg_dump` and `pg_restore` (PostgreSQL 16 or newer) via local
clients, or the existing local Docker db with verified cluster identity. A remote DB
requires native clients. The check runs version commands, not a database dump. Invalid
configuration, wrong/unreachable database, unwritable directories or missing backup
tools stop startup with Ukrainian instructions and clean up this launcher's children.
An occupied port belonging to another program is reported without terminating it.
Preflight does not contact AI, MT5 or Whisper; missing optional services do not prevent
manual/offline journal functionality. Directory checks create and remove only unique
probe files. Migration backup inspection reads TOC and every data block with pg_restore
without restoring anywhere; failure blocks the upgrade and leaves existing data intact.

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
| `make migrate` | back up the DB, then apply Alembic migrations (see below) |
| `make db-ensure` | start the DB if needed and migrate, then exit |
| `make install` | install backend and frontend dependencies |

Without make: `python scripts/dev.py [--no-browser | --ensure-db | --stop]`.

**Backups before migrations.** `start.bat`, `make dev`, `make db-ensure` and `make migrate`
apply migrations through `python -m app.tools.migrate`: when a migration is pending on the
dev DB it first runs `pg_dump -Fc` (host `pg_dump`, or `docker compose exec db pg_dump` for a
local Docker DB) to `backups/pre-migration-<revision>-<UTC time>.dump`, prints the path and
never automatically prunes pre-migration archives (M7 PM decision). If the backup fails,
the migration is not applied. Databases ending in `_test` are not backed up.
Restore drills must target a newly created isolated database, never the dev database
or existing QA data; verify schema and data before considering recovery. Local backups
do not protect against physical disk failure. A raw
`alembic upgrade head` bypasses the backup.

**Verified one-shot backup (M7-01).** From normal PowerShell in the repo root:
`uv run --project backend python -m app.tools.backup` creates a manual backup of the
configured application DB. Optional `--root "D:\JournalBackups"` changes the destination
(default `backups/`, gitignored; keep external folders private and outside version control).
Manual and pre-migration archives are never automatically deleted. Explicit `--kind daily`
creates a daily archive and then retains the union of 14 daily, 8 weekly and 6 monthly
verified representatives, selected by Europe/Brussels periods. No automatic scheduler
is installed in M7-01. Publication includes `archive.dump` and checksum `manifest.json`
in a target-hashed folder; PostgreSQL TOC/data inspection and SHA-256 detect damage.
A scope `.lock` left after a crash requires confirming no backup process is active
before an owner removes that lock; never remove a live process's lock.

**Daily scheduling and status (M7-02).** The normal worker runs one verified daily
backup at **18:00 Europe/Brussels**, following both DST changes. API and PostgreSQL
must be healthy; optional AI/MT5 availability does not prevent a backup. A dedicated
executor keeps dumping separate from MT5 synchronization. With the app/laptop off,
no backup runs. On startup/wake, one latest missed slot is caught up after health is
confirmed; older missed dates are not replayed and the next 18:00 slot is preserved.
Failures have at most three attempts per due slot, at least five minutes between
attempt starts; recovery is checked every 15 seconds. The next daily slot gets a new
budget. Successful publication is reconciled across restarts without another dump.

`BACKUP_DIR` configures a private local destination for worker, API and CLI (default
repo `backups/`; CLI `--root` still overrides it). Use the same stable configuration
for API and worker. Change it only with the app stopped; it owns both archives and
the per-target scheduler journal, so a new empty directory starts new schedule history.
Do not remove/edit `schedule.json` or move archives during normal operation.
The permanent `.schedule.lock` is an OS lock file, not a stale lock to delete.
M7-01's separate `.lock` may survive a hard crash during pg_dump: the UI explains the
block, and retries never forcibly unlock it. Stop the app and have the engineer verify
the associated dump/restore processes before resolving that lock. Corrupt state or
archive also requires inspection; never delete it just to make the warning disappear.

Every page → bottom status bar → **«Резервні копії»** shows last successful copy,
failed attempts, overdue state, next schedule/retry and actionable Ukrainian errors.
The API offers read-only `/api/backups/status`, also included in `/api/health`.
Status polling does not hash archives. Timestamps show Brussels time in the UI;
the journal stores UTC. Retention failures retain success and show a warning; retention
is tried again after the next successful daily backup. Local disk and sudden-power-loss
limitations from M7-01 still apply. See `docs/reports/M7-02.md` for synthetic evidence
and the owner checks requiring a real scheduled backup.

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

### Running the worker without a terminal (demo / QA)

The worker reads MT5 through a data source chosen by `MT5_SOURCE` in `.env`:

- `MT5_SOURCE=real` (default): the MetaTrader5 terminals of the accounts.
- `MT5_SOURCE=fixture:<path to JSON>`: recorded data from `backend/tests/fixtures/mt5/`
  (path relative to the repo root), no terminal needed. Example:
  `MT5_SOURCE=fixture:backend/tests/fixtures/mt5/basic_week.json`. Create an active account
  with the fixture's login and server (`51234567` @ `FundedNext-Server` for `basic_week.json`,
  see `backend/tests/fixtures/mt5/README.md`) and set any non-empty
  `MT5_PASSWORD_51234567=...`. The worker then syncs it like a real account (the log warns
  that fixture data is in use). Remove the line to go back to real terminals.

The worker syncs every active account (status `active`; passed/failed/archived accounts are
skipped) one after another: every 60 s during trading hours, every 15 min otherwise
(`sync` in `config/rules.yaml`). Each attempt is a row in `sync_log`; failures show in the
UI status bar and in `logs/worker.log`.

## Logs

- `logs/api.log`, `logs/worker.log`: rotating log files (UTC timestamps). Errors shown in the
  UI are logged here with details.
- Each name retains one active UTF-8 file up to 5 MiB and five numeric archives
  (`.1` newest to `.5` oldest): 30 MiB per name, 60 MiB for API/worker together.
  A permanent `.log.lock` serializes cooperating process writes and rotation; do not
  delete it while the app runs. Files close between writes for Windows-safe rotation.
  External exclusive file locks cause a sanitized stderr warning; close the external
  handle to allow later writes to recover. Console errors remain visible.
- Formatted messages/tracebacks redact configured secrets and recognized credential
  syntax; records above 64 KiB receive a truncation marker. Never deliberately log
  secrets. Historical files are preserved. `ai_usage.jsonl` is an unrotated audit file;
  application rotation never cleans it, audio, backups or unrelated files.
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

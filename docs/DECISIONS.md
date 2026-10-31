# Technical decisions

One line per decision: date, decision, reason. Product decisions live in PRD.md.

- 2026-10-31: Monorepo layout `backend/` (uv project, package `app`), `backend/app/worker/` for the worker, `frontend/`, `config/`, `scripts/`, `docker/`, `logs/`, `data/`. Reason: ROADMAP M0 allows `backend/worker`; one Python project means shared models and one venv.
- 2026-10-31: Local Postgres 16 via `docker-compose.yml` (service `db`, port 5432) as the default; a native install works by changing `DATABASE_URL`. Reason: no native Postgres on the dev laptop, Docker Desktop is installed; PRD 5 requires both to work.
- 2026-10-31: Test DB is a second database `trading_journal_test` in the same Postgres, created by `docker/postgres-init/`. Tests use `TEST_DATABASE_URL` and recreate the schema per session. Reason: simplest throwaway DB, no testcontainers dependency.
- 2026-10-31: Sync SQLAlchemy 2.x with `psycopg` (v3) driver, sync FastAPI endpoints. Reason: single local user, simpler code and tests than async; worker is a separate process anyway.
- 2026-10-31: API prefix `/api`, backend on 127.0.0.1:8000, Vite dev server on 127.0.0.1:5173 proxies `/api`. Reason: no CORS setup, localhost-only per PRD 3.
- 2026-10-31: Decimal values (money, prices, volumes) are serialized in JSON as strings; DB columns use `NUMERIC`. Reason: no float rounding in money math (backend-dev rule).
- 2026-10-31: Error responses use `{ "error": { "code", "message", "details" } }`; the frontend maps `code` to Ukrainian text in `uk.ts`, falling back to a generic message. Reason: UI text stays in one i18n file; backend logs stay English.
- 2026-10-31: npm (ships with Node) as the frontend package manager. Reason: nothing extra to install on a fresh clone.
- 2026-10-31: `make dev` and `start.bat` both call one Python launcher `scripts/dev.py` (starts DB if needed, runs migrations, starts API, worker, frontend, opens browser). Reason: one cross-shell implementation instead of duplicating logic in Makefile and batch.
- 2026-10-31: GNU make on Windows via `winget install ezwinports.make`; Makefile recipes use only commands valid in both cmd and sh. Reason: CLAUDE.md requires `make check`; Windows has no make by default.
- 2026-10-31: Frontend versions: React + Vite 8 + TypeScript 6 (strict + noUncheckedIndexedAccess), Tailwind 4 via @tailwindcss/vite, react-router 8, TanStack Query 5, ESLint 9 (eslint-plugin-react not yet on ESLint 10). Reason: current stable, plugin compatibility.
- 2026-10-31: `react/jsx-no-literals` is an ESLint error (props and a few symbols allowed). Reason: enforces "no hardcoded UI strings" from CLAUDE.md.
- 2026-10-31: Non-envelope HTTP errors (e.g. Vite proxy 502) map by status: 5xx → network_error, 404 → not_found, 422 → validation_error, else unknown. Reason: backend down shows "Сервер недоступний".
- 2026-10-31: Toasts dedupe by error code; queries opt out with `meta.silentError` (health poll uses it). Toasts are neutral-coloured; green/red reserved for P&L and deviations. Reason: PRD style rule, no toast spam.
- 2026-10-31: shadcn/ui components added by hand only when used (button, sonner); fixed dark theme, no next-themes. Reason: no unused code.
- 2026-10-31: Backend versions: FastAPI 0.162, Starlette 1.10, SQLAlchemy 2.1, psycopg 3.3, Alembic 1.20, APScheduler 3.11; build via hatchling, version from package metadata.
- 2026-10-31: Health: engine connect_timeout 2 s, `SET LOCAL statement_timeout=2000` in the health check; `db.error` is a fixed short English string by exception type, details only in logs. On Windows a refused port surfaces as a ~2 s timeout.
- 2026-10-31: Unhandled exceptions handled by a middleware (logs traceback once, returns internal_error); custom error codes via `ApiError(status, code, message, details)`.
- 2026-10-31: Logging: rotating 5 MB × 5 files, UTC ISO timestamps; `setup_logging(file_name)` shared by API (`api.log`) and worker (`worker.log`).
- 2026-10-31: Tests point DATABASE_URL at the test DB and LOG_DIR at a temp dir before importing the app; pytest treats warnings as errors (one Starlette TestClient deprecation ignored).
- 2026-10-31: Alembic migrations named `YYYYMMDD_<rev>_<slug>`; env.py honours an explicit `config.attributes["sqlalchemy.url"]` so migration tests can target the test DB.
- 2026-10-31: Schema numeric types: money NUMERIC(18,2), prices/volumes/tick values NUMERIC(20,8), percent/R NUMERIC(10,4); all datetimes TIMESTAMPTZ; system enums VARCHAR + CHECK; journal option fields VARCHAR(50) without CHECK (options live in YAML, old values survive).
- 2026-10-31: Accounts with trades cannot be deleted (FK RESTRICT), they are archived; symbol_specs and sync_log cascade with the account; trade/bias children cascade with their parent.
- 2026-10-31: Bias alignment stored as computed daily/weekly/monthly values plus `bias_alignment_override` + reason; effective value = override if set. Values: aligned/counter/neutral_bias/no_bias.
- 2026-10-31: trades.weekday (0 = Monday) and hour (0–23) are Brussels time of the open. bias_entries.period_date is a Brussels date (trading day; Monday for weekly; 1st for monthly). Digest periods are inclusive dates.
- 2026-10-31: `updated_at` bumped by the ORM (no DB trigger). Tests rebuild the test DB by dropping `public` and running Alembic `upgrade head`; a drift test fails if models and migrations diverge.
- 2026-10-31: Open positions are stored as trades with status `open` and close_time NULL (CHECK enforces the pair); the inbox only uses needs_sl/needs_description/draft. Default status for a closed trade is needs_description.
- 2026-10-31: accounts keep the last synced MT5 `balance`, `equity`, `balance_synced_at` (calculator offline, daily/weekly limits). trades.last_sl and trade_exit_deals.reason (MT5 DEAL_REASON, lowercase, no CHECK so unknown broker values never break sync) support breakeven detection.
- 2026-10-31: A custom test compares CHECK constraints between models and the migrated DB, because Alembic's comparison ignores them.
- 2026-10-31: Worker uses APScheduler BackgroundScheduler (UTC, coalesce, max_instances=1); main thread waits on a threading.Event in 1 s slices so Ctrl+C/SIGTERM/SIGBREAK stop it promptly on Windows; every job wrapped to log and swallow exceptions.
- 2026-10-31: Launcher (`scripts/dev.py`): children in their own process group, stopped with `taskkill /T /F` on Windows (no orphans); frontend starts in parallel with DB check + migrations; ports 8000/5173 fixed (match vite.config.ts); deps re-installed when lock/manifest is newer than a stamp file; port-busy check by exclusive bind; auto-starts Docker Desktop (wait ≤120 s) only for a local DB host; Node ≥ 20.19 (Vite 8); console messages English, UI Ukrainian.
- 2026-10-31: `scripts/` is linted/type-checked with the backend ruff/mypy config via explicit Makefile paths; `make test` runs `dev.py --ensure-db` first so `make check` works on a fresh clone.

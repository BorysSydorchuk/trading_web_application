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

# STATUS

Current milestone: **M0 Foundation** (in progress)

## Environment notes (dev laptop)
- Python 3.12.9, Node 24, npm 10, Docker Desktop 29, git.
- Installed for this project: `uv` 0.13.1 (`pip install --user uv`), GNU make 4.4.1 (`winget install ezwinports.make`).
- No native Postgres; DB runs in Docker (`docker compose up -d db`).

## M0 tasks

- [x] T1 Repo scaffold: `.gitignore`, `.env.example`, `docker-compose.yml` + test DB init, `Makefile` targets, folders (orchestrator)
- [x] T2 Backend core: uv project, pydantic-settings, logging to `logs/`, DB engine/session, error handlers, `GET /api/health`, ruff/mypy/pytest config, tests (backend-dev)
- [x] T3 Frontend shell: Vite React TS, Tailwind + shadcn/ui, dark theme, router + sidebar (7 pages, empty states), `i18n/uk.ts`, API client, global error toast, status bar polling health, eslint + tsc (frontend-dev) — parallel with T2
- [ ] T4 DB schema: SQLAlchemy models + first Alembic migration for PRD 6.1–6.9 (accounts, symbol_specs, trades, trade_exit_deals, chart_links, audio_notes, bias_entries, digests, rule_violations, sync_log), migration tests (backend-dev)
- [ ] T5 Worker stub: separate process with APScheduler, logs heartbeat, no MT5 yet (backend-dev)
- [ ] T6 Launch: `scripts/dev.py`, `make dev`, `start.bat`, README setup from fresh clone (backend-dev)
- [ ] T7 QA: fresh-clone run per AC, `make check` green, AC verification notes (qa-tester)
- [ ] T8 M0 report `docs/reports/M0.md` (orchestrator)

Each task: implement → `make check` → code-reviewer APPROVE → commit.

## Log
- 2026-10-31: Read PRD/ROADMAP, created STATUS/DECISIONS/BACKLOG/api.md, planned M0.
- 2026-10-31: T1 scaffold committed (0b83d41). T3 frontend shell reviewed (1 fix: Ukrainian page title) and committed (3dfa494). T2 backend core approved and committed (688566e). T4 schema in progress.

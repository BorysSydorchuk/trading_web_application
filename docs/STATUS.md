# STATUS

Current milestone: **M1 MT5 sync and trade data** (in progress). M0 accepted by PM 2026-11-01.

## Environment notes (dev laptop)
- Python 3.12.9, Node 24, npm 10, Docker Desktop 29, git.
- Installed for this project: `uv` 0.13.1 (`pip install --user uv`), GNU make 4.4.1 (`winget install ezwinports.make`).
- No native Postgres; DB runs in Docker (`docker compose up -d db`).

## Where we stopped / how to resume (updated continuously)
Last update: 2026-11-02. Borys asked to finish the sprint; M1-01, M1-06, M1-11 agents resumed.
Committed in M1: M1-02 config, M1-03 domain, M1-04 accounts API, M1-05 Settings UI, M1-07 rules engine, M1-09 trades/inbox/sync API, M1-10 sync chips/badge/notifications.

Uncommitted work left in the tree (PARTIAL — not reviewed, check before use):
- M1-01 launcher (scripts/dev.py, start.bat, stop.bat, Makefile, README.md, backend/tests/test_dev_script.py): feature built and verified; review asked for 3 fixes, agent was stopped mid-fix:
  1. start Docker Desktop outside our process tree (`cmd /c start "" <exe>`) so taskkill /T never kills it;
  2. check taskkill return code + re-check the process is gone before printing "Зупинено"; in start mode fail if ours survived; test with a kill that leaves the process alive;
  3. README example `Зупинено: api uv.exe (PID 1234).`
  Some of fix 1–3 may be half-applied: run `pytest tests/test_dev_script.py` and re-review.
- M1-06 MT5 source (backend/app/mt5/ partial, backend/pyproject.toml + uv.lock with MetaTrader5/tzdata deps): stopped mid-build (protocol/adapter stage). No fixtures, recorder, tests or docs/MT5_SETUP.md yet. Last known: mypy errors in app/mt5/types.py. Easiest: restart the task from its spec (see M1 tasks) keeping or discarding app/mt5/.
- M1-11 Journal + Inbox UI (frontend/src/features/journal/, features/trades/, components/MultiSelectFilter.tsx, edits in api/client.ts, inbox/*, i18n/uk.ts, lib/decimal.ts, lib/time.ts): stopped mid-build (table/detail dialog stage). Needs: run lint/typecheck, finish, review. Backend for it (M1-09) is committed. Must add `errors.trade_open` and client-side SL checks (positive, != entry, below entry for buy / above for sell).

Next after those: M1-08 sync service + worker job (needs M1-06; also wire violation recompute into PATCH initial_sl), M1-12 trade check table tool (needs M1-06), M1-13 QA, M1-14 live demo check Monday + docs/reports/M1.md.
To resume: read CLAUDE.md, this file, DECISIONS.md; `git status`; finish/verify each partial task above, code-review, commit. Per-agent test DBs exist: trading_journal_test_a..d.

## M1 tasks

Wave 1 (parallel):
- [ ] M1-01 Launcher clean restart: run file with PIDs, auto-stop our previous run when ports are busy, `stop.bat`; Docker Desktop check/start with 60 s wait; Ukrainian console messages (backend-dev)
- [x] M1-02 Config loaders: `config/rules.yaml` + `config/journal_fields.yaml` (PRD 6.4 fields) with validation, `GET /api/journal-fields`, `GET /api/rules` (backend-dev)
- [x] M1-03 Domain logic (pure, no DB): broker time ↔ UTC (ny_close rule, offset detection, DST tests), session classification, trade building from deals (partial closes, scaling in, VWAP), initial SL selection, computed fields (risk, R, planned RR, P&L %, balance at open, weekday/hour, re-entry) (backend-dev)
- [x] M1-04 Accounts API + migration (drop password_ref, add trades.initial_sl_source), `.env.example` MT5 keys (backend-dev)
- [x] M1-05 Settings page: accounts CRUD (frontend-dev)

Wave 2:
- [ ] M1-06 MT5 source: read-only wrapper over `MetaTrader5` + fixture source + fixture recorder script; `docs/MT5_SETUP.md` (backend-dev)
- [x] M1-07 Rules engine v1 (PRD 6.9) on top of domain logic (backend-dev)
- [ ] M1-08 Sync service + worker job: sequential accounts, upserts, open positions, status transitions, specs, balance, offset, sync_log, cadence from rules.yaml (backend-dev)
- [x] M1-09 Trades/inbox/sync-status API (backend-dev)
- [x] M1-10 UI: status bar per-account sync state + sidebar inbox badge + browser notification (frontend-dev)
- [ ] M1-11 UI: Journal table (filters, sort, column chooser) and Inbox list with SL input (frontend-dev)
- [ ] M1-12 Trade check table tool for the 5-trade comparison (backend-dev)
- [ ] M1-13 QA: fixture scenarios end-to-end through mock source, AC verification (qa-tester)
- [ ] M1-14 Live check with demo account (Monday, markets open Sun 23:00 Brussels) + M1 report (orchestrator + Borys)

## M0 tasks

- [x] T1 Repo scaffold: `.gitignore`, `.env.example`, `docker-compose.yml` + test DB init, `Makefile` targets, folders (orchestrator)
- [x] T2 Backend core: uv project, pydantic-settings, logging to `logs/`, DB engine/session, error handlers, `GET /api/health`, ruff/mypy/pytest config, tests (backend-dev)
- [x] T3 Frontend shell: Vite React TS, Tailwind + shadcn/ui, dark theme, router + sidebar (7 pages, empty states), `i18n/uk.ts`, API client, global error toast, status bar polling health, eslint + tsc (frontend-dev) — parallel with T2
- [x] T4 DB schema: SQLAlchemy models + first Alembic migration for PRD 6.1–6.9 (accounts, symbol_specs, trades, trade_exit_deals, chart_links, audio_notes, bias_entries, digests, rule_violations, sync_log), migration tests (backend-dev)
- [x] T5 Worker stub: separate process with APScheduler, logs heartbeat, no MT5 yet (backend-dev)
- [x] T6 Launch: `scripts/dev.py`, `make dev`, `start.bat`, README setup from fresh clone (backend-dev)
- [x] T7 QA: fresh-clone run per AC, `make check` green, AC verification notes (qa-tester)
- [x] T8 M0 report `docs/reports/M0.md` (orchestrator)

Each task: implement → `make check` → code-reviewer APPROVE → commit.

## Log
- 2026-10-31: Read PRD/ROADMAP, created STATUS/DECISIONS/BACKLOG/api.md, planned M0.
- 2026-10-31: T1 scaffold committed (0b83d41). T3 frontend shell reviewed (1 fix: Ukrainian page title) and committed (3dfa494). T2 backend core approved and committed (688566e). T4 schema in progress.
- 2026-10-31: T4 schema: review requested balance/equity, last_sl, deal reason, CHECK drift test; fixed, approved, committed (45f25f0). T5 worker: private-API override replaced with public API, approved, startup-failure nit fixed by orchestrator, committed (6278ef4). T6 launcher in progress.
- 2026-10-31: T6 launcher: review found password-fragment leak in URL errors, README PowerShell command, missing tests, double Ctrl+C; fixed, approved, committed (47394f4). T7 QA fresh clone: AC pass except fixed Docker container_name broke a second checkout → removed; npm install quieter; README notes cmd prompt. M0 report written.
- 2026-11-01: M0 accepted. M1 planned (rules.yaml, api.md M1 contract, decisions written).
- 2026-11-01: Committed M1-04 (8053c0b), M1-05 (eec7fb5), M1-03 (cebf099), M1-02 (223facc), M1-10 (0a38909), M1-07 (2714eac).
- 2026-11-01: M1-09 committed (e33f4a5). Agents stopped on request; partial M1-01/M1-06/M1-11 left uncommitted (see resume notes).

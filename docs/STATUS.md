# STATUS

Current milestone: **M2 Describe a trade (text + links)** (in progress). M1 accepted by PM 2026-11-03 (open item: 2-minute live check, Borys reports the time; >2 min → first M2 bug). M0 accepted 2026-11-01.

## Environment notes (dev laptop)
- Python 3.12.9, Node 24, npm 10, Docker Desktop 29, git.
- Installed for this project: `uv` 0.13.1 (`pip install --user uv`), GNU make 4.4.1 (`winget install ezwinports.make`).
- No native Postgres; DB runs in Docker (`docker compose up -d db`).

## Where we stopped / how to resume (updated continuously)
Last update: 2026-11-03, agents stopped on Borys's request.

M2 status: M2-01 (Program Files guard), M2-02 (contract), M2-03 (journal save API), M2-05 + M2-06 (Describe screen, AI usage in Settings) are reviewed, merged into main and pushed. make check green on main (772 backend tests; frontend lint/typecheck).

In progress: **M2-04 AI extraction** on branch `m2/ai-extraction` (pushed). One WIP commit, NOT reviewed, `make check` not run: settings split (ANTHROPIC_MODEL_EXTRACTION / _SUMMARY / _FALLBACK / _EFFORT), `anthropic` dep added, config/ai_pricing.yaml + loader, services/ai/client.py, services/ai/usage_log.py, domain/extraction.py. Agent stopped while writing the system prompt (backend/prompts/extract_trade.md) and loader. Still to do for M2-04: prompt + loader, schema builder from YAML (with evidence), guards, POST /api/trades/{id}/extract, GET /api/ai/usage, tests, fixture format for QA, .env.example. Resume: `git switch m2/ai-extraction`, run `make check`, give backend-dev the original M2-04 brief (this file's M2-04 line + docs/api.md "AI extraction"/"AI usage" + DECISIONS 2026-11-03) and say what already exists; then code-reviewer, merge --no-ff, push.

Then: M2-07 extraction fixtures (10 texts UA/RU/EN, Sonnet time/cost per call, compare with Opus if quality is clearly worse → numbers to PM), M2-08 QA end-to-end against the real backend (Describe screen was only clicked through against a mock API) + docs/reports/M2.md (commit range: first M2 commit 6686f93 "docs: M2 plan"), then Borys describes 3 real trades (needs ANTHROPIC_API_KEY in .env).

Open questions for Borys: (1) OK to add Vitest (frontend dev dependency) for tests of chartLinks/formModel/aiMerge/serverErrors? (2) CLAUDE.md security-reviewer line refers to a Telegram bot that no longer exists: point it at M7 Hardening or delete?

Leftover: folder `.claude/worktrees/agent-a532538fd24d93aac` could not be deleted (Windows lock); it is gitignored and no longer a git worktree, delete it by hand when nothing runs. Per-agent test DBs trading_journal_test_a..d exist.
To resume: read CLAUDE.md, this file, DECISIONS.md; `git status`; continue M2-04.

## M2 tasks

Git: one branch per topic `m2/<topic>`, merge `--no-ff` after code-reviewer APPROVE + green `make check`, push main after each merge.

- [x] M2-01 Settings rejects terminal paths under Program Files (env vars, both slashes, case, 8.3, `..`), worker guard too; Ukrainian error → MT5_SETUP.md step 1; tests (backend-dev, then frontend-dev for uk.ts) — branch m2/terminal-path-guard
- [x] M2-02 M2 API contract in docs/api.md (journal save, chart links, extract, AI usage) + decisions (orchestrator) — branch m2/contract
- [x] M2-03 Journal save API: `PUT /api/trades/{id}/journal`, validation generated from journal_fields.yaml (types, options, deprecated, extra storage), required check for complete, status flow, user violations, TradingView link validation + preview_url; test: new YAML field works without code changes (backend-dev) — branch m2/journal-save
- [ ] (WIP on m2/ai-extraction) M2-04 AI extraction: `anthropic` SDK (needs Borys OK), prompt in backend/prompts/ with glossary, schema from YAML with evidence quotes, server guards (evidence, options, questions), errors (ai_not_configured / ai_error), usage log logs/ai_usage.jsonl + config/ai_pricing.yaml + `GET /api/ai/usage` (backend-dev) — branch m2/ai-extraction
- [x] M2-05 Describe screen: auto data left; text box + links; "Заповнити з тексту" with progress; form generated from /api/journal-fields with AI markers, red missing fields, "Не вистачає: …"; save draft / complete; inbox → describe (frontend-dev) — branch m2/describe-ui
- [x] M2-06 (done inside M2-05) Settings: AI month-to-date cost + model + "key not set" state (frontend-dev) — branch m2/ai-usage-ui
- [ ] M2-07 Extraction fixtures: 10 sample texts (UA/RU/EN mix, glossary terms) with expected fields; tests that fail on a question or a field not mentioned in the text; optional live eval `make ai-eval` (qa-tester) — branch m2/extraction-fixtures
- [ ] M2-08 QA end-to-end + M2 report (qa-tester + orchestrator)

## M1 tasks

Wave 1 (parallel):
- [x] M1-01 Launcher clean restart: run file with PIDs, auto-stop our previous run when ports are busy, `stop.bat`; Docker Desktop check/start with 60 s wait; Ukrainian console messages (backend-dev)
- [x] M1-02 Config loaders: `config/rules.yaml` + `config/journal_fields.yaml` (PRD 6.4 fields) with validation, `GET /api/journal-fields`, `GET /api/rules` (backend-dev)
- [x] M1-03 Domain logic (pure, no DB): broker time ↔ UTC (ny_close rule, offset detection, DST tests), session classification, trade building from deals (partial closes, scaling in, VWAP), initial SL selection, computed fields (risk, R, planned RR, P&L %, balance at open, weekday/hour, re-entry) (backend-dev)
- [x] M1-04 Accounts API + migration (drop password_ref, add trades.initial_sl_source), `.env.example` MT5 keys (backend-dev)
- [x] M1-05 Settings page: accounts CRUD (frontend-dev)

Wave 2:
- [x] M1-06 MT5 source: read-only wrapper over `MetaTrader5` + fixture source + fixture recorder script; `docs/MT5_SETUP.md` (backend-dev)
- [x] M1-07 Rules engine v1 (PRD 6.9) on top of domain logic (backend-dev)
- [x] M1-08 Sync service + worker job: sequential accounts, upserts, open positions, status transitions, specs, balance, offset, sync_log, cadence from rules.yaml (backend-dev)
- [x] M1-09 Trades/inbox/sync-status API (backend-dev)
- [x] M1-10 UI: status bar per-account sync state + sidebar inbox badge + browser notification (frontend-dev)
- [x] M1-11 UI: Journal table (filters, sort, column chooser) and Inbox list with SL input (frontend-dev)
- [x] M1-12 Trade check table tool for the 5-trade comparison (backend-dev)
- [x] M1-13 QA: fixture scenarios end-to-end through mock source, AC verification (qa-tester) — 9/9 pass, screenshots docs/reports/M1-screens/; found: passed/failed accounts show stale chip → fix M1-13a
- [x] M1-13a Sync status lists only active accounts (backend-dev)
- [x] M1-14 Live check with real FundedNext account + M1 report (orchestrator + Borys): 30-day count matches, trade-check 5/5, error + recovery, browser auto-open; 2-minute test pending on next real trade

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
- 2026-11-02: M1-01, M1-06, M1-08, M1-11, M1-12 committed; make check 546 passed. M1-13 QA started then stopped on request; qa DBs dropped.
- 2026-11-02: M1-13 QA restarted from scratch (qa-tester).
- 2026-11-03: M1-13 QA done: 9/9 scenarios pass (README match, trade-check 5/5, inbox 64 s, error+recovery, PATCH SL, screenshots, launcher, make check 547). M1-13a fixed. Note for M1-14: 2-min AC holds inside trading hours only (night cadence 900 s by design); confirm real error code of a closed terminal.
- 2026-11-03: M1-13a committed (sync status only active accounts). Waiting for Borys for M1-14.
- 2026-11-03: Borys: M1 stays on main (chore/ecc-setup was a stale pointer, deleted). From M2, one branch per milestone `m<N>/<topic>` (rule added to CLAUDE.md).
- 2026-11-03: M1-14 live check by Borys passed (2-min test pending on next real trade). MT5_SETUP.md fixes applied. docs/reports/M1.md written. Stopped for PM review.
- 2026-11-03: M1 accepted by PM. PM decisions + git workflow recorded, main pushed. M2 planned; M2-01 started.
- 2026-11-03: M2-01, M2-02, M2-03, M2-05/06 merged. M2-04 started, stopped on request (WIP commit on m2/ai-extraction).

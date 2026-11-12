# STATUS

Current milestone: **M6 Dashboard and digests** (from 2026-11-12). M5 accepted 2026-11-12. M4 PM-approved 2026-11-07 with deferred checks. M3 accepted 2026-11-05, M2 accepted 2026-11-04, M1 accepted 2026-11-03, M0 accepted 2026-11-01.

## Environment notes (dev laptop)
- Python 3.12.9, Node 24, npm 10, Docker Desktop 29, git.
- Installed for this project: `uv` 0.13.1 (`pip install --user uv`), GNU make 4.4.1 (`winget install ezwinports.make`).
- No native Postgres; DB runs in Docker (`docker compose up -d db`).

## Where we stopped / how to resume (updated continuously)
Last update: 2026-11-08 (M5-01/02 full checks green and final independent general/Python APPROVE; local commit/merge next, then M5-03 metadata and margin persistence).
Merged into local main and green (`make check`: 1211 backend + 1 skipped real-model test, 216 frontend): M3-01 contract, M3-02 number words, M3-03 AI warm-up, M3-04 transcription backend (code-reviewer + database-reviewer APPROVE), M3-05 component tests, M3-06 voice recorder UI (code-reviewer APPROVE after fixes), M3-07 required-since (code-reviewer + database-reviewer APPROVE, fixes e63609d, merge 4d4bbd4; make check 1248 backend + 216 frontend), M3-08 new-fields UI (code-reviewer APPROVE, fixes fe171f2, merge e32f109; frontend 229 tests). No open m3/* branches.

**M3-09 QA done (docs/reports/M3-qa.md): 2-min AC FAILS with defaults (small int8 beam 5: 47–72 s on Russian TTS stand-in audio; laptop throttles under sustained load; spikes from Whisper temperature fallback). Recommendation: keep small, re-measure with Borys's voice, then try WHISPER_BEAM_SIZE=1 (.env only); limiting the fallback = code change, PM decision. Failure/retry PASS (API/worker). No browser checks done (left for Borys). QA DB `trading_journal_qa_m3` left in Postgres. Next: get 3 recordings from Borys, re-bench beam 5/1, then M3-10.** Original M3-09 plan: (qa-tester: real timing for 30 s / 1 min / 2 min notes with `make whisper-bench FILES=...` and end to end through the UI; small int8, and base too if 2 min > 30 s total; failure + retry; mic denied; then ask Borys for 3 recordings of his voice as fixtures), M3-10 live check by Borys + docs/reports/M3.md.

Notes for the next session:
- faster-whisper `small` is already downloaded on this laptop (HF cache, took ~14 min); model load ~1.4 s. PyAV pinned < 19 (faster-whisper 1.2.1 incompatibility, guarded by a default test).
- For Borys: add to .env.example (all optional, defaults shown): WHISPER_MODEL=small, WHISPER_COMPUTE_TYPE=int8, WHISPER_LANGUAGE=uk (empty = auto-detect), WHISPER_BEAM_SIZE=5, WHISPER_CPU_THREADS=0, DATA_DIR=data. Agents must not edit .env/.env.example.
- PM question for the M3 report: the structured-output grammar cache expires 24 h after last use (Anthropic docs), so the first AI fill after a quiet day is ~25 s even without a YAML change; hash-only warm-up doesn't cover it (option: also warm up when the last warm-up is > 24 h old, ~0.30 USD/month).
- Leftover worktree folders under .claude/worktrees/ (gitignored) may remain if Windows locked them; delete by hand.
To resume: read CLAUDE.md, this file, DECISIONS.md; `git status`; start M3-07.

## M4 tasks

Git: one branch per topic `m4/<topic>` from main, merge `--no-ff` after code-reviewer APPROVE + green `make check`. Never push. Migrations → database-reviewer. Whisper: no repeated runs without asking Borys.

- [x] M4-01 Plan, API contract (docs/api.md "## M4"), decisions (orchestrator)
- [x] M4-02 (code-reviewer APPROVE; live eval of "Сетап H4, H1 Flow" and "…, але H1 проти H4" to add to the M4 live check) M3 follow-ups: AI warm-up by time (start if last successful AI call > 20 h, Mon–Fri 07:30 Brussels) + prompt rule "Сетап H4, H1 Flow" → setup_context yes, with fixture (backend-dev) — branch m4/m3-followups
- [x] M4-03 (database-reviewer + code-reviewer APPROVE, fixes 3782baf; dev DB at b6d41a9e2c57 with the period_date index, 0 bias rows) Bias DB + config: `bias_notes` table, bias_entries.bias_note_id, audio_notes.bias_entry_id → bias_note_id, `config/bias.yaml` loader, `GET /api/bias/config` (backend-dev, database-reviewer) — branch m4/bias-schema
- [x] M4-04 (code-reviewer APPROVE, fixes fe35d1c) Bias alignment domain (pure) + recompute service for trades on note create/edit/delete and on sync (backend-dev) — branch m4/bias-core (with M4-05)
- [x] M4-05 (merged with M4-04) Bias API: notes CRUD, by-period, result marking, bias audio upload, status/reminders (backend-dev) — branch m4/bias-core
- [x] M4-06 (code-reviewer APPROVE, fixes afd9fbf; aliases EUR/USD GBP/USD GBP XAU/USD XAU фибер added) Bias extraction: prompt, per-symbol schema, guards, fixtures (UA/RU/EN, aliases) (backend-dev) — branch m4/bias-extraction
- [x] M4-07 (code-reviewer APPROVE, fixes 7d3404f; not yet seen in a browser) Bias page: list, note form (kind, date, recorder + audio file, text, "Заповнити з тексту", per-symbol cards, links), "біас був правильний" marking (frontend-dev) — branch m4/bias-ui
- [x] M4-08 (combined recovery: full checks + production build green; independent code-reviewer APPROVE) Головна bias status + reminders, sidebar badge; alignment daily/weekly/monthly in Journal + Describe (frontend-dev) — branch m4/bias-dashboard
- [x] M4-09 QA (offline evidence, full checks and independent general/Python APPROVE; owner live checks reserved for M4-10) (fixtures, AC: daily + weekly entries, trade alignment, pre_ny reminder after 12:30; ≤ 3 Whisper runs) + docs/reports/M4-live-check.md + scripts/qa_live_check_m4.py (qa-tester, orchestrator)
- [ ] M4-10 Live check by Borys + docs/reports/M4.md (orchestrator)

## M3 tasks

Git: one branch per topic `m3/<topic>`, merge `--no-ff` after code-reviewer APPROVE + green `make check`. Never push. Migrations → database-reviewer.

- [x] M3-01 M3 API contract (docs/api.md "## M3") + decisions (orchestrator) — branch m3/contract
- [x] M3-02 Number words from code to `config/extraction.yaml` (loader, validation, reload); tests for "4", "четвірка", "четвёрка", "four", "на 4 з 5", ambiguous → empty (backend-dev) — branch m3/number-words
- [x] M3-03 AI warm-up in the worker on schema-hash change (`data/ai_warmup.json`, purpose `warmup`); find out what causes the ~25 s first call and write it in DECISIONS (backend-dev) — branch m3/ai-warmup
- [x] M3-04 Transcription backend: `faster-whisper` dep, settings, `config/transcription.yaml` glossary, audio upload/get/file/retry, worker queue job with progress, migration for progress/error_code (backend-dev, database-reviewer) — branch m3/transcription
- [x] M3-05 Frontend test setup: jsdom + Testing Library + MSW (dev only), first component tests (frontend-dev) — branch m3/component-tests
- [x] M3-06 Reusable hold-to-record component + Describe screen integration: upload, progress, transcript into the editable text box, failed → message + retry + replay, mic denied / no mic message (frontend-dev) — branch m3/voice-ui
- [x] M3-07 Required-since: table + migration, `missing_required` by close time, `missing_new_fields`, `GET /api/trades?missing_new_fields=true` (backend-dev, database-reviewer) — branch m3/required-since
- [x] M3-08 Journal filter "Неповні за новими полями" + new-field hint on Describe (frontend-dev) — branch m3/new-fields-ui
- [x] M3-09 QA (2-min AC fails with defaults, see M3-qa.md): real timing for 30 s / 1 min / 2 min notes on this laptop (small int8; base too if 2 min > 30 s), failure + retry, mic denied, end-to-end; 3 fixtures of Borys's voice (qa-tester)
- [x] M3-11 Whisper tuning: beam 1, VAD, condition_on_previous_text off, temperatures 0,0.4, physical-core threads, all via .env; bench `--preset old`, `--show-text` (backend-dev; review fix: old preset VAD on) — merged be96db5
- [x] M3-12 "Завантажити аудіо" button in the recorder (.ogg/.opus/.m4a/.mp3/.wav/.webm, 25 MiB, by extension) (frontend-dev) — merged 187a084
- [x] M3-13 (FAIL on terms, time OK; results in docs/reports/M3-qa.md, commit 403b5a0; PM decides: recommendation new defaults + WHISPER_CONDITION_ON_PREVIOUS_TEXT=true, 82 s note 19.9 s, 120 s est. 29–30.5 s; AI fill not measured: key 401) QA timing matrix on Borys's recordings (data/qa-voice, never commit): 3 files × beam 1/5 × old/new (+ new with condition_on_previous_text on, which kept terms correct in a 1-file run), median of 3, total = upload + transcription + AI fill, terms FVG/IFVG/QM/POI/BOS/SMT + symbols; add to docs/reports/M3-qa.md. If 2-min > 30 s: stop, report to PM (qa-tester)
- [x] M3-14 docs/reports/M3-live-check.md (b8c29ff), ≤ 12 items, mic items marked (orchestrator)
- [x] M3-15 Bug from live check: Describe labels mojibake. Cause: live-check PowerShell 5.1 Get-Content/Set-Content double-encoded the config copy in %TEMP%	j-qa-config (Python already read UTF-8). Real config/journal_fields.yaml NOT modified (checked: `git diff main -- config/` empty, `git status config/` clean), nothing to restore. Fix: utf-8-sig config reads, AST encoding guard test, mojibake config refused (config_error reason mojibake, Ukrainian UI text naming the file), scripts/qa_live_check.py replaces PowerShell edits (backend-dev, frontend-dev; code-reviewer APPROVE after fixes)
- [x] M3-16 Transcript term normalization config/transcript_glossary.yaml (worker, before done) + condition_on_previous_text default True (backend-dev; code-reviewer APPROVE) — merged 7225676. Extra rules beyond the PM list (assumption for the report): ФТА→FTA, МТ5/МТ-5→MT5, М1/М15/М30
- [x] M3-17 AI key status: startup models.retrieve check, POST /api/ai/check, health `ai`, usage `key_state`; status bar chip + Settings (backend-dev, frontend-dev; code-reviewer APPROVE) — merged f30381b, afe4e1d. LOW left: rare race where a check started before an extraction auth error can overwrite invalid_key with ok
- [x] M3-18 (PASS: 82 s note 15.7 s median, key fields right in all runs; 392110c) End-to-end QA on Borys's 3 recordings (transcribe → normalize → extract), max 3 runs each (PM limit, laptop ~95 °C): total time + which fields right; pass = 82 s note ≤ 30 s median and POI type, entry model, FVG kind, timeframes right in all 3. Needs a valid API key (qa-tester)
- [ ] M3-10 Live check by Borys (non-mic items now) + docs/reports/M3.md (orchestrator)

## M2 tasks

Git: one branch per topic `m2/<topic>`, merge `--no-ff` after code-reviewer APPROVE + green `make check`, push main after each merge.

- [x] M2-01 Settings rejects terminal paths under Program Files (env vars, both slashes, case, 8.3, `..`), worker guard too; Ukrainian error → MT5_SETUP.md step 1; tests (backend-dev, then frontend-dev for uk.ts) — branch m2/terminal-path-guard
- [x] M2-02 M2 API contract in docs/api.md (journal save, chart links, extract, AI usage) + decisions (orchestrator) — branch m2/contract
- [x] M2-03 Journal save API: `PUT /api/trades/{id}/journal`, validation generated from journal_fields.yaml (types, options, deprecated, extra storage), required check for complete, status flow, user violations, TradingView link validation + preview_url; test: new YAML field works without code changes (backend-dev) — branch m2/journal-save
- [x] M2-04 AI extraction: `anthropic` SDK (needs Borys OK), prompt in backend/prompts/ with glossary, schema from YAML with evidence quotes, server guards (evidence, options, questions), errors (ai_not_configured / ai_error), usage log logs/ai_usage.jsonl + config/ai_pricing.yaml + `GET /api/ai/usage` (backend-dev) — branch m2/ai-extraction
- [x] M2-05 Describe screen: auto data left; text box + links; "Заповнити з тексту" with progress; form generated from /api/journal-fields with AI markers, red missing fields, "Не вистачає: …"; save draft / complete; inbox → describe (frontend-dev) — branch m2/describe-ui
- [x] M2-06 (done inside M2-05) Settings: AI month-to-date cost + model + "key not set" state (frontend-dev) — branch m2/ai-usage-ui
- [x] M2-07 (live eval done 2026-11-04: Sonnet 90.7% p95 3.8 s 0.0102 USD; Opus 90.8% p95 4.9 s 0.0214 USD) Extraction fixtures: 10 sample texts (UA/RU/EN mix, glossary terms) with expected fields; tests that fail on a question or a field not mentioned in the text; optional live eval `make ai-eval` (qa-tester) — branch m2/extraction-fixtures
- [x] M2-08 QA end-to-end + M2 report (qa-tester + orchestrator)
- [x] M2-09 Vitest + 147 frontend logic tests in make check (frontend-dev)

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
- 2026-11-04: M2 done: live eval (Sonnet 90.7 %, p95 3.8 s), Borys check OK, M2 report written. Stopped for PM review.
- 2026-11-04: M2 accepted by PM. M3 planned (contract, 10 tasks).
- 2026-11-04: M3-02, M3-03, M3-05 merged. M3-04 and M3-06 on branches (not merged). Stopped on request.
- 2026-11-04: Resumed; M3-04 and M3-06 reviewed, fixed, merged. Stopped on request before M3-07.
- 2026-11-04: M3-07 required-since done (table + marker, sync in API and worker, missing_new_fields, list filter), reviewed, merged.
- 2026-11-04: M3-08 Journal filter + Describe new-fields note done, reviewed, merged. Screens not yet seen in a browser (check in M3-09).
- 2026-11-04: M3-09 QA report: 2-min note 47–72 s with small beam 5 (FAIL), failure/retry pass; waiting for Borys's recordings.
- 2026-11-05: PM review applied. M3-11 + M3-12 merged (make check 1310 + 262). 1-file bench: new defaults 10.9 s vs old 22.1 s, but condition_on_previous_text off loses IFVG/H4/H1/FTA; on keeps them at 12.1 s (PM decision). Borys's .env has WHISPER_BEAM_SIZE=5 and WHISPER_CPU_THREADS=0 (override new defaults).
- 2026-11-05: M3-13 matrix on Borys's 3 recordings (19/41/82 s): new b1 time OK (82 s → 18.4 s + ~2.2 s AI est.) but IFVG/H4/H1/Flow/M5/FTA wrong; newcond b1 terms OK except "FVG H1" (no config) and one Cyrillic ФВГ, 19.9 s. No symbols/QM/BOS/SMT spoken. AI key 401 since after 2026-11-04 21:48 UTC. Stopped per PM rule; live-check list written. Waiting for PM.
- 2026-11-05: M3-15 mojibake bug (live-check PowerShell step) fixed, reviewed, merged; real config unchanged. make check 1394 + 273.
- 2026-11-05: PM M3 decision: Whisper default condition_on_previous_text on, transcript glossary, AI key check; acceptance now by extracted fields. Git history: no real Anthropic key (only fake test strings). M3-16/M3-17 merged, make check 1513 + 293. Waiting for Borys's key.
- 2026-11-05: Borys: valid key, .env Whisper overrides removed, main pushed (055fb2e), extra glossary rules approved. M3-18 PASS. M3 report written; waiting for live check 1–8.
- 2026-11-05: M3 accepted by PM (live check 1–8 ✅). PM answers: time-based warm-up, setup_context rule. M4 planned (10 tasks).

## Prior Codex safe-shutdown checkpoint - 2026-11-06T13:11:49+00:00

- Active: M4-08 reconciliation/verification; branch `m4/bias-dashboard`, HEAD `b948009`. No recovery commits or pushes. M4-08 remains unchecked; M4-09 planning only; M4-10 not started.
- Preserved both sessions' frontend work, including Home narrowing and six Home/Sidebar tests. Original untracked `scripts/pyproject.toml` / `scripts/uv.lock` untouched (SHA256 `2560C9D7C16F2ABB555AF5493A889C83ADA12E55B320A790126BB094E1C5D9FD` / `E63F1ADEBBB85D847090327CCD9E7F73795CD7A79099DA3827633B20718C3A32`).
- Added uncommitted `AGENTS.md`, `.codex/config.toml`, ten `.codex/agents/*.toml`; updated existing DECISIONS/STATUS. Frontend uncommitted paths: components/layout/Sidebar.tsx; features/bias/{api,types}.ts; features/describe/{TradeSummary.tsx,trade.fixture.ts}; features/journal/columns.ts; features/trades/{BiasAlignmentLabel.tsx,TradeCell.tsx,types.ts}; i18n/uk.ts; pages/{HomePage.tsx,HomePage.test.tsx,DescribePage.test.tsx,JournalPage.test.tsx}. No application edits by this recovery session.
- Workflow/model checks: Codex 0.167.0 strict app-server config validation passed; catalogs list required models. Runtime thread metadata confirms root Astra and architect child Sol; all three children explicitly spawned with gpt-6.1-sol, fresh context and matching Claude role path. Architect discovery finished; frontend-dev read-only reconciliation found no substantiated defect; qa-tester read-only M4-09 plan finished. All agents completed/stopped; no independent final review yet. Agents made no edits/tests/DB calls.
- Verification: backend/frontend lint, ruff format, backend/script mypy and frontend tsc passed. Full `make check` first interrupted at ~60% backend, then restarted after owner corrected usage to 23%; second interrupted at ~56% when owner reported 15%. Both stopped with Ctrl+C and exit 1, no test failure observed; neither is a passing full run. 1775 backend tests collected, real-model test skipped as expected. Frontend full tests and build not reached/revalidated this session; historical 337 tests/APPROVE are not current combined verification. Controlled execution sessions 36236 and 37869 ended. Shutdown check found no pytest/make-check/vitest processes and zero other test-database connections.
- DB: PostgreSQL 127.0.0.1:5432; real app DB `trading_journal` not modified. Both DATABASE_URL and TEST_DATABASE_URL were pinned to `trading_journal_test` for checks, including db-ensure migrations. Zero other connections before each run. Existing `trading_journal_test_m4_08_codex`, `trading_journal_qa_m3`, and test_a/b/c/d databases preserved; no M4 QA DB created or database deleted. Disposable test schema is partially exercised after cancellation; rebuild only after idle-target verification. No live MT5/AI/Whisper calls; Whisper count 0.
- Resources: original three .claude/worktrees entries preserved (m3/audio-file-upload, m4/bias-ui, m3/ai-key-status-ui). Test fixtures created temporary tj-test-logs-/tj-test-data- directories; left intact, no cleanup performed. No live-check server launched.
- Blocker/limitation: sandbox helper fails before command launch (`helper_unknown_error: setup refresh had errors`); approved require_escalated commands work. No reliable automatic 5-hour allowance tool exposed; owner reading required at boundaries. Latest owner reading 15%; stop now, no automatic resume. Workflow permission prohibitions are instruction-level adaptations, not imported Claude tool ACLs.

### Historical shutdown resume instructions (superseded below)

1. Resume **M4-08 full verification and independent final review**. Read this checkpoint first, AGENTS.md, CLAUDE.md, docs/PRD.md, ROADMAP.md, DECISIONS.md and api.md M4. Ask for current allowance if unavailable; do not resume automatically after reset.
2. Check branch/HEAD/diff and active test processes/DB connections. Run complete `make check` as one runner, loading the configured test URL internally, asserting host 127.0.0.1 and database trading_journal_test, and setting BOTH DATABASE_URL and TEST_DATABASE_URL to it in the child environment; clear ANTHROPIC_API_KEY. This avoids make db-ensure migrating the real journal. Run frontend production build too. Never print credentials.
3. After green checks, give independent code-reviewer the full diff including added files, changed-file list and verification results. Fix actual findings, reverify, then commit locally with explicit paths, excluding original scripts/pyproject.toml and scripts/uv.lock. Merge topic --no-ff only with green checks and APPROVE. Earlier session approvals do not satisfy current final review.
4. Continue M4-09 after M4-08 commit. Minimal proposal: QA owns scripts/qa_live_check_m4.py, backend/tests/test_qa_live_check_m4.py and docs/reports/M4-live-check.md; root owns STATUS/DECISIONS. Pin dedicated trading_journal_qa_m4, separate TEMP tj-qa-m4 config/data, unchanged copied config, fixture MT5 and offline AI by default (avoid inherited API key causing warmup). Guard targets before filesystem/DB changes; do not reuse M3 launcher directly (it pins M3 DB and changes lesson). Existing 11 extraction fixtures and bias API/domain/service tests cover core scenarios; add tests only for actual gaps and launcher safety. Distinguish fixture/API evidence from pending browser/live checks.
5. Do not repeat Whisper benchmarks, live AI calls, external account operations or destructive DB cleanup without applicable owner authorization. Preserve QA databases/worktrees/original untracked files. Never push. Prepare M4 live-check evidence and M4-10 checklist, then stop before **Borys's M4-10 owner acceptance**; never approve on his behalf.

- 2026-11-06 resume: owner explicitly said continue and reported allowance reset expected shortly (not independently confirmed). Root restarted full make check in execution session 50942 after confirming no test runners/other DB connections; both DB URLs pinned to trading_journal_test and AI key cleared. Frontend production build passed. Previous shutdown checkpoint remains historical; update final verification before committing.


## Historical M4-08 verification checkpoint

- Owner confirmed allowance reset / >15%. Full check completed successfully: 1774 backend passed, 1 intentionally skipped real-Whisper test (437.63 s); 337 frontend passed (23 files). All Makefile lint/type checks and separate production build passed. No real AI/Whisper/MT5 calls. Full run session 50942 ended with exit 0.
- Independent `code-reviewer` (gpt-6.1-sol) APPROVE covers combined M4-08 and ten-role workflow mapping. No actual implementation defect found. Previous interrupted verification notes above are historical.
- Next: commit reviewed M4-08/workflow locally, preserve original untracked scripts/pyproject.toml and scripts/uv.lock, then M4-09 on its own topic after local merge per conventions. Root remains sole integration/DB runner. M4-09 launcher/guard tests/live-check report plan is in the historical checkpoint above; implement that minimal scope and record automated vs owner-live evidence separately.
- Required final gate: M4-10 live check/acceptance by Borys. Never push. No QA DB deletion, repeated Whisper runs, or real-account operations.


## Safe-shutdown checkpoint - 2026-11-06T17:39:57+00:00

- Active milestone/task: M4 Bias / M4-09 QA. Branch `m4/bias-qa`, HEAD `b58f6c2`. M4-08 commit `24943b7`, independently APPROVED, merged locally with --no-ff as `b58f6c2`. No push. M4-10 owner acceptance not started.
- M4-08 verified: complete make check 1774 backend passed / 1 intentionally skipped real-Whisper test, 337 frontend passed; all lint/type checks and production build passed. Independent code-reviewer APPROVE covered UI plus workflow recovery. Original two-session contributions preserved. Models: Astra main, all children explicitly Sol; ten native role mappings retained.
- M4-09 partial work (uncommitted): `scripts/qa_live_check_m4.py`, `backend/tests/test_qa_live_check_m4.py`, `docs/reports/M4-live-check.md` from qa-tester; root added draft `docs/reports/M4.md` and updated STATUS. Root retains STATUS/DECISIONS; QA agent owns the three QA files. All agents finished; no ongoing delegated work.
- QA launcher: exact local psycopg3 URL for trading_journal_qa_m4, separate TEMP tj-qa-m4 config/data/logs, unchanged marked config copy, fixture MT5, AI forced off, no DB create/reset/delete. Reuses existing M3 process/config validation helpers. Original scripts/pyproject.toml and scripts/uv.lock remain untracked and unchanged; never stage them.
- Verification: RED 18 expected missing-launcher errors before implementation. GREEN 20 guard tests passed in 0.27 s; strict mypy on new script passed. Root found PT018 and formatter mismatch; qa-tester fixed and formatted. Latest full make check session 15692 stopped by Ctrl+C/exit 1 during frontend lint on owner 15% report: backend ruff check passed, format 188 files passed; frontend lint completion/type/tests not established for M4-09. No final independent M4-09 code/Python review yet; do not commit or mark M4-09 complete.
- Actual isolated acceptance evidence PASS: NEW trading_journal_qa_m4 created non-destructively, migrated, seeded via real sync with basic_week fixture (7 trades). Real API handlers/TestClient+PostgreSQL created daily/weekly/monthly notes, validated date normalization, journal/detail alignment and note IDs, historical edit recompute and manual result. Injected 2026-10-19 clock: pre_ny reminder false at 12:29 Brussels, true at 12:30, cleared on note creation. This is fixture/API evidence, not browser/live-model evidence.
- Preserved QA seed: trade 1 / pos2000101 EURUSD buy, trade 2 / pos2000201 GBPUSD sell, date 2026-10-19. Notes 1 pre_london EURUSD bullish, 2 pre_ny GBPUSD bearish, 3 weekly both bearish (2026-10-19), 4 monthly both neutral (2026-10-01). EURUSD aligned/counter/neutral_bias; GBPUSD aligned/aligned/neutral_bias. Entry1 marked correct. Other fixture trades IDs 3-7. Reproduction/evidence in ignored `logs/m4_qa_evidence.py` and `logs/m4-qa-evidence.json`; script refuses existing seed, DO NOT rerun over preserved data.
- DB safety: full check pinned BOTH DB URLs to idle trading_journal_test, AI key cleared; real trading_journal not modified. QA/test_m4_08_codex/M3/test_a-b-c-d databases retained. No real MT5/AI/Whisper calls; M4 Whisper count 0. No browser tool available; owner visual/mic/live checks pending. Normal app ports 8000/5173 were already occupied (PIDs 26196/30240); root did not stop or launch over that app. Full launcher smoke was therefore not run. No new live server/background app started by recovery.
- Resources/blockers: sandbox process helper still fails; approved require_escalated commands work. No automatic reliable usage reading; latest owner 15%, shutting down now. Original worktrees and temp test dirs retained; no cleanup authorized. Existing app processes are owner-owned, leave them running.

### Historical resume instructions (superseded below)

1. Resume **M4-09 verification, review, and completion**, not M4-08. Read this latest checkpoint, AGENTS.md, CLAUDE.md, docs/ROADMAP.md, DECISIONS.md/api.md M4, and new M4/M4-live-check reports. Check current allowance with owner if unavailable. Wait for authorized resume after reset.
2. Inspect Git status (branch m4/bias-qa, HEAD b58f6c2), new files and processes/DB targets. Complete `make check` with BOTH DATABASE_URL and TEST_DATABASE_URL set internally to confirmed idle local trading_journal_test and ANTHROPIC_API_KEY empty; sole runner only. Also run strict mypy for `scripts/qa_live_check_m4.py` explicitly (not in Makefile script list). Frontend application code unchanged since verified M4-08 build.
3. Review launcher safety/owner instructions. Real launcher smoke remains pending because normal app ports are occupied: do not stop the owner app without authorization. Existing config validation/launch sequencing tests use stubs. Keep offline vs live evidence explicit.
4. After green full checks, supply full diff/added files, changed-file list and evidence to independent code-reviewer plus Python reviewer for new .py code. Address findings, reverify as needed. Update reports/STATUS with final totals; commit only approved files, excluding scripts/pyproject.toml and uv.lock. Merge locally --no-ff only after APPROVE+green checks. Never push.
5. Finalize M4-09 offline QA report and M4-10 acceptance checklist in existing prepared reports. Do not claim full milestone/browser/voice/live-AI acceptance. Stop before **Borys's M4-10 acceptance**; provide him the live-check steps and pending M4-02 phrase/M3 mic followups.
6. Do not rerun seed creation, reset/delete QA databases, run repeated Whisper/live AI/real account operations, or discard any uncommitted work. Preserve normal app, QA data/audio, original untracked files and old worktrees. Cleanup needs owner authorization.

## Recovery verification - 2026-11-06T22:30:00Z

- Branch m4/bias-qa, HEAD b58f6c2; original untracked scripts/pyproject.toml and scripts/uv.lock hashes match the shutdown checkpoint. Existing worktrees preserved.
- Owner authorized resume and reported 98%, then 55% before independent reviews. No automatic allowance source is exposed. Ten role mappings remain Sol, root configuration Astra; native runtime supports required Sol model.
- Sole runner: root. Complete make check passed: 1794 backend / 1 intentional real-Whisper skip (99.95 s), 337 frontend (23 files); all lint/type checks and separate strict launcher mypy passed. Both DB URLs pinned to verified idle local trading_journal_test; AI disabled. Initial sandbox cache-denied attempt did not reach tests.
- Docker Desktop restarted after reboot; existing PostgreSQL container and databases retained. Actual offline QA launcher smoke passed with HTTP 200 health/frontend, expected seeded alignment and AI not_configured; controlled stop succeeded. QA seed not recreated, no queued audio, no live AI/Whisper/MT5 calls. No owner app was running or stopped.
- Independent Sol code-reviewer and python-reviewer both APPROVE, no substantive findings. Reviewers ran no tests or modifying commands; both finished. M4-09 is complete. M4-10 browser/voice/live-AI owner acceptance remains pending.
- Git integration: reviewed five-file topic m4/bias-qa, commit subject test(bias): complete M4-09 offline QA and owner checklist; local --no-ff merge to main after green checks/APPROVE. Full M4 implementation range 9a1ebe9..m4/bias-qa. No push. Original scripts manifests remain untracked and unchanged.
- Resources: smoke launcher exited 0, ports 8000/5173 free, no controlled test/app processes left. Existing Docker/PostgreSQL kept running; no QA databases removed.

### Historical resume instructions (superseded by M5 PM authorization)

1. **Stop before M4-10 owner acceptance.** M4-09 implementation, full verification, launcher smoke and independent reviews are complete. Borys should use docs/reports/M4-live-check.md; do not repeat completed M4-08/M4-09 work.
2. Preserve QA DB/audio, original untracked scripts manifests and worktrees. Do not rerun seed creation or repeat Whisper/live AI.
3. Stop before M4-10; Borys executes docs/reports/M4-live-check.md and provides owner/PM acceptance. No push.

## M5 bootstrap safe-shutdown checkpoint - 2026-11-06T23:06:29Z (2026-11-07 Brussels)

- Owner authorized M5 and approved M4. Live rows 1-8 passed; 9-10 deferred to Monday 2026-11-09 12:30-16:00 Brussels; optional mic/Whisper 11 skipped; final review 12 deferred; live-AI requires explicit authorization. Journal detail-card bias added to BACKLOG, nonblocking.
- Usage: owner 25% at bootstrap, then 12%; stop development, no automatic resume. No reliable automatic usage source.
- Git: branch m5/calculator-plan, HEAD e5994be (M4-09 merge; task commit 6e18319). New uncommitted documentation only: STATUS, DECISIONS, BACKLOG, reports/M4.md and M4-live-check.md. No M5 code or formula changes. Original untracked scripts/pyproject.toml and scripts/uv.lock preserved; old worktrees untouched. No commit: this documentation increment has not received complete checks/independent review.
- Workflow: existing root Astra configuration and ten explicit Sol role configs verified unchanged; one explicit Sol architect assigned read-only assessment, asked to finish immediately at 12%. Root remains sole integration/DB runner. No tests, app launches, migrations, resets, live accounts, AI or Whisper performed this bootstrap; process check found no python/make/node processes. QA databases/audio retained, DB state not rechecked this turn.
- Existing calculator page is a placeholder. Account reference_balance/current balance and timestamp, symbol tick/volume specs and synced_at exist. Architect found no leverage/calc mode/point/margin rates/FX inputs; Mt5Source lacks margin method and legacy allow-list test excludes order_calc_margin despite PRD 6.8 requiring it. Existing fixtures are synthetic FundedNext-like, not verified owner terminal specs. No margin formula chosen or approved.
- Architect finished safely; all agents idle/completed, no outstanding delegated edits. Proposed (not yet accepted API contract): GET /api/accounts/{id}/symbol-specs and POST /api/calculator/calculate; pure domain position_size.py; shared frontend form; keep MT5 ownership in worker, consider bounded DB-backed margin requests with migration review. Capture actual point rather than assume 10^-digits; assess loss/profit tick-value asymmetry. TDD must cover arbitrary volume steps, below-minimum refusal (never round up), maximum cap, risk <= budget, SL direction, percent/amount equivalence and RR targets. Final M5 requires a defensible offline margin estimate or explicit PM scope decision; unavailable margin alone would not fulfill PRD.

### Historical M5 shutdown instructions

1. Obtain fresh owner allowance and authorized resume. Read this checkpoint and current PM decision; do not re-block M5 on deferred M4 checks. Preserve all five documentation edits and original untracked manifests.
2. Finish M5-01 architecture/API plan in existing docs/api.md and STATUS before code. Read architect findings and inspect MT5 source/guard, account/spec models and fixture README. Confirm real FundedNext specs provenance with Borys for EURUSD/GBPUSD/XAUUSD/GER40; do not label synthetic tests as real-spec acceptance. Resolve missing offline margin inputs/estimation contract without inventing a trading formula.
3. Split implementation: mandatory tdd-guide first for Decimal sizing/round-down/risk/TP edge tests (>=80% sizing coverage), backend-dev pure core then API/read-only margin integration, frontend-dev shared calculator form/page and compact Home panel; database-reviewer if migration needed. Root sole test runner. Agree API before parallel edits; exclusive file ownership.
4. Complete full make check on verified idle local trading_journal_test with BOTH DB URLs pinned and AI disabled; independent review before any commit/merge, no push. Do not rerun M4 seed creation, Whisper or live AI; no QA DB deletion.
5. M5 acceptance remains Borys comparing four symbol calculations to MT5 within one volume step. M4 rows 9-10 remain scheduled Monday; row 12 and live-AI authorization remain open.

## M6 tasks

Git: one branch per topic `m6/<topic>` from main, merge `--no-ff` after code-reviewer APPROVE + green `make check`. Never push. Contract: docs/api.md "## M6". All % of account size, canonical symbols.

- [x] M6-01 [S] plan, API contract, decisions (orchestrator), branch m6/plan
- [ ] M6-02 [L] digest metrics domain (pure): metrics, breakdowns + coverage, rules/bias sections, norm/deviation, chart data (tdd-guide tests first, backend-dev; python-reviewer), branch m6/digest-metrics. RED observed 2026-11-12 (55 tests, commit 5861fa0); backend-dev implementing. `digest.deviation_sigma` config moved to M6-04 (module takes k as a parameter)
- [ ] M6-03 [L] dashboard API: today/week P&L per account vs limits, shared sticky-extremes function with the rules engine, stop flags, open positions, inbox (tdd-guide, backend-dev), branch m6/dashboard-api
- [ ] M6-04 [L] digests API: generate/regenerate, list, get, by-period, review PATCH, suggestion, next_bias_note_id (backend-dev; database-reviewer only if a migration appears), branch m6/digests-api
- [ ] M6-05 [M] Home dashboard UI: limits + «СТОП на сьогодні/тиждень» banner, inbox, open positions, sync per account, quick links, digest suggestion (frontend-dev), branch m6/dashboard-ui
- [ ] M6-06 [M] Digests UI: list, digest page (metrics with red/green, breakdowns, rules, bias, SVG charts), review form + next-period bias note on one screen (frontend-dev), branch m6/digests-ui
- [ ] M6-07 [M] AI summary: `POST /api/digests/{id}/ai-summary` + button (backend-dev, frontend-dev), branch m6/digest-ai
- [ ] M6-08 [L] QA: fixture week hand-calculated (win rate, total R, P&L, PF, DD), deviation fixture, browser check; owner check on one real week + docs/reports/M6.md

## M5 tasks

PRD 6.8 and ROADMAP M5 remain authoritative. Owner acceptance requires four real FundedNext symbol comparisons against MT5 within one volume step; synthetic cases are not that evidence.

- [x] M5-01 architecture/API contract and recorded M4 approval (root, architect assessment complete)
- [x] M5-02 pure Decimal sizing core, financial TDD and >=80% coverage (tdd-guide then backend-dev; root runner)
- [x] M5-03 broker point/loss tick-value capture and margin persistence, migration review (backend-dev, database-reviewer)
- [x] M5-04 calculator API + margin (PM scope check 2026-11-09: sizing from symbol_specs, never MT5; margin secondary). Owners: claude (no codex task open)
  - [x] M5-04a (code-reviewer APPROVE after fixes; make check 1990+1 skip / 337; real no-op run and real docker dump verified) pre-migration pg_dump backup for non-test DBs (backend-dev) + process rules, scripts manifests, M4 live eval/report (orchestrator), branch m5/premigration-backup
  - [x] M5-04b (database-reviewer + code-reviewer APPROVE; make check 1995+1 skip / 337; LOW: samples CHECK names + empty-table asserts added, DECISIONS data-loss note) migration 80ae699b47ce dropping calculator_margin_samples and signature columns (backend-dev, database-reviewer), branch m5/calculator-api
  - [x] M5-04c (code-reviewer APPROVE; python-reviewer APPROVE after fixes: NUL/surrogate symbol 422, 160-digit margin scaling, details.fields always, NaN → 409; MarginInfo frozen; 232 focused, coverage core 97% / service+schema 100%; make check 2124+1 skip / 337) `GET /api/accounts/{id}/symbol-specs`, `POST /api/calculator/calculate` incl. cached estimate (tdd-guide tests first, backend-dev), branch m5/calculator-calculate
  - [x] M5-04d (code-reviewer + python-reviewer APPROVE, fix batch re-approved: stale processing sweep 261 s + de-dup bound, finish warnings, storable guard tests; make check 2255+1 skip / 337) margin requests API + worker job + read-only `order_calc_margin` (allow-list) + fixture source (backend-dev), branch m5/margin-requests. Open LOW: run_margin_cycle returns None after a finish() failure (logged).
- [x] M5-05 (code-reviewer APPROVE after fixes: no generic toast on domain errors, margin failure reason shown, stale result guards; 392 frontend tests; make check 2255+1 skip / 392; build OK; not yet seen in a browser → M5-06) reusable calculator page and compact Home panel, Ukrainian UI (frontend-dev), branch m5/calculator-ui
- [x] M5-06 (code-reviewer + python-reviewer APPROVE; synthetic QA + root Chrome browser check PASS; make check 2316+1 skip / 392; hardening LOWs → BACKLOG) isolated QA, full regression and independent reviews (qa-tester, root runner, reviewers), branch m5/calculator-qa
- [x] M5-08 (database-reviewer + code-reviewer APPROVE, python-reviewer APPROVE after fixes; make check 2473+1 skip / 398; migration 5d2e8b1c4a90) canonical symbols / GER30 alias (Borys M5-07 finding) (backend-dev, frontend-dev, database-reviewer), branch m5/canonical-symbols
- [x] M5-09 (database-reviewer APPROVE; code-reviewer + python-reviewer APPROVE after fix batch; make check 2684+1 skip / 406; migration f6ea0d1af419) cross-currency loss value (Borys M5-07 GER40 FAIL 2026-11-11: tick_value 0.12 stale, real 0.11091): fx_rates + order_calc_profit check, calculator rate display, trade-risk fallback; contract docs/api.md "M5-09" (tdd-guide, backend-dev, frontend-dev, database-reviewer), branch m5/fx-conversion
- [x] M5-10 (database-reviewer APPROVE; code-reviewer + python-reviewer APPROVE after fix batch; make check 2758+1 skip / 413; migration a3e7c91d5b20) risk base = account size (PM 2026-11-11): reference_balance NOT NULL «Розмір рахунку», all % of it, recompute stored trades + rules; contract docs/api.md "M5-10" (tdd-guide, backend-dev, frontend-dev, database-reviewer), branch m5/risk-base
- [x] M5-11 [tier M] PM process change: change tiers in CLAUDE.md/DECISIONS; pytest-xdist (one test DB per worker), test-backend on db-up (no dev DB migrate); make check 844 s → 93 s, branch m5/fast-checks
- [x] M5-07 owner real-spec/MT5 comparisons: GER40 PASS 2026-11-12 (lot 0.13, risk 92.89, margin 2 538.82 MT5, rate 1.10609 = order_calc_profit 0.11060908); EURUSD/GBPUSD/XAUUSD OK 2026-11-10. **PM: M5 ACCEPTED 2026-11-12.**
- [x] M5-12 [tier S] close M5: report with owner table, real-spec unit tests (specs synced for 11459118 on 2026-11-12), branch m5/close-report

Root owns docs and all test execution; TDD owns backend/tests/domain/test_position_size.py; backend will own app/domain/position_size.py after observed RED. No overlapping edits or real terminal operations. Architect margin design uses dated broker-derived samples for explicitly labelled offline estimates, no guessed leverage formula. Existing API/schema extended only in later tasks.

### Historical M5 continuation instructions

Continue M5-01/02: finish core tests, root observes RED, backend implements pure core, root runs targeted coverage and complete make check, independent review before local commit/merge. Subsequent API and schema work follows the M5 contract in docs/api.md. Preserve M4 follow-ups and original untracked scripts manifests. No push, no live AI/Whisper/real accounts. Owner real-spec evidence request pending.


### M5-01/02 current evidence (2026-11-07)

- Owner explicitly resumed and reported allowance reset 100%; owner subsequently reported 32% before full verification/reviews.
- Architect assessed official MetaQuotes docs and proposed worker-only live margin plus dated cached estimate. Contract recorded in docs/api.md; no margin/schema/API implementation yet.
- Financial TDD RED: missing app.domain.position_size, one collection error in 1.45 s. Backend implemented only pure app/domain/position_size.py. GREEN: 97 tests passed in 0.48 s, 97% core statement coverage. Root sole runner; no DB fixture used by these pure tests. Full gate running after owner 32% reading. First attempt stopped at three test-only mypy dynamic-replace errors; root corrected annotations, all lint/type checks passed on rerun.
- Root formatter applied. Ruff initially found nine PT011 broad ValueError assertions; TDD agent fixed them with category-specific matches. Root rerun: formatting and lint passed, 97 tests passed in 0.50 s, 97% coverage. No financial defect observed yet. No independent M5 review or commit yet.
- Real FundedNext specs/MT5 four-symbol evidence requested from owner and still pending. Synthetic oracles are labelled. Full M5 acceptance is not claimed.

- All M5 architect/TDD/backend agents completed; no controlled tests or app processes remain. Branch m5/calculator-plan, HEAD e5994be; six documentation files plus new domain module/test remain uncommitted. Current operation: full make check with both URLs pinned to idle local trading_journal_test and AI disabled, then independent general/Python review of complete diff. Do not repeat RED or real-model runs.

- Subsequent full gate: 1891 backend passed / 1 intentional skip, frontend 336 passed / 1 unchanged DescribeVoice 5000ms timeout. Isolated DescribeVoice rerun passed all 15 tests without changes. Owner then reported allowance reset 100%; complete gate retry underway on verified idle test DB. Do not count the timeout run as a green full gate.

- Complete gate retry PASSED: 1891 backend / 1 intentional real-Whisper skip (110.93 s), 337 frontend (23 files, 13.67 s), all Makefile lint/type checks. No frontend code changed; prior voice-test timeout retained as transient evidence after isolated and full reruns passed. Independent general/Python review next; no M5 commit yet.

- Independent general review APPROVE; Python review requested bounds on Decimal representation/working precision (extreme compact exponent could force billions of digits). TDD added safe context-sentinel regression: RED 3 failed/3 boundary passed in0.36s without allocating extreme arithmetic. Backend fix in progress; reverify before final approval/commit.


## Safe-shutdown checkpoint - 2026-11-07T16:05:27Z

- Owner reported allowance reset100%, then13% during final verification. Stop development now; no automatic resume. No reliable automatic usage tool. No new assignments or reviews after13%.
- Active task M5-01 contract/M5-02 pure sizing core. Branch m5/calculator-plan, HEAD e5994be. No M5 commits/merges/pushes. Six modified docs: BACKLOG.md, DECISIONS.md, STATUS.md, api.md, reports/M4-live-check.md, reports/M4.md. Two new files: backend/app/domain/position_size.py and backend/tests/domain/test_position_size.py. Original scripts/pyproject.toml and scripts/uv.lock remain untracked and unchanged; never stage them. Existing worktrees retained.
- Work: M4 approval/deferred checks recorded; M5 architecture/contract documented. Pure Decimal core implements sizing, effective-balance input, SL price/points, tick/grid validation, volume floor/cap/min refusal, actual risk and directional RR targets. API/schema/margin/worker/frontend are NOT implemented. Existing historical trade metrics unchanged.
- Agents: Sol architect assessment, Sol TDD tests, Sol backend implementation finished. General code reviewer APPROVE covered pre-fix increment. Python reviewer CHANGES REQUESTED found unbounded input-exponent precision; backend fixed representation limits. Both reviewers completed; neither has finally approved the changed fix. Root sole runner. No active delegated edits.
- Financial TDD: original RED absent module; GREEN97tests/97%coverage. Full gate initially hit test-only mypy errors (fixed), later one unchanged DescribeVoice5000ms timeout. Isolated15voice tests and subsequent full gate passed unchanged:1891backend+1intentional real-Whisper skip,337frontend (110.93s/13.67s). This full pass predates the resource fix.
- Review fix: maximum64coefficient digits, Decimal exponent[-64,64], working precision<=8192; reject before context allocation. Safe sentinel regression RED3failed/3boundary passed in0.36s, no huge arithmetic allocation. Post-fix targeted GREEN103tests in0.25s,96%core coverage. One RUF043 regex-string lint issue corrected to raw string afterward. No financial formula changed.
- Final full make check (session62514): lint, formatting190files, backend/script mypy and frontend tsc passed;1898backend tests collected and progressing without observed failure. Interrupted with Ctrl+C/exit1 at owner13%; NOT a passing final run, frontend final stage not established. Prior output wait cell106 was terminated; controlled test execution then stopped. No commit without final green gate and approval.
- DB/resources: all full gates set BOTH DATABASE_URL and TEST_DATABASE_URL to verified idle local127.0.0.1:5432/trading_journal_test (server container172.20.0.2), AI key empty. Test schema may be partially exercised; check idle before next rebuild. No QA DB deletion/reset; QA data/audio and existing Docker kept. No app server launched, no real MT5/AI/Whisper calls. One intentional real-model test remains skipped.
- Owner evidence pending: real FundedNext specs and four MT5 comparisons; repository fixtures remain synthetic. M4 approved:rows1-8 passed,9-10 Monday2026-11-09 12:30-16:00Brussels,11optional mic skipped,12review deferred,liveAI requires explicit authorization. Journal detail-card bias is nonblocking BACKLOG; Describe works.

### Historical shutdown resume instructions

1. Obtain fresh allowance and explicit resume; read this latest checkpoint. Preserve the eight uncommitted task files and two original untracked manifests. Do not restart implementation or repeat completed RED stages.
2. As sole runner, check no active tests/other test-DB connections; run complete make check with BOTH DB URLs pinned to confirmed local trading_journal_test and AI disabled. Do not reset/delete QA databases or rerun seed scripts. Post-fix103tests/96%coverage already passed; only rerun focused tests if code changes justify it.
3. After green full gate, regenerate logs/m5-core-review-packet.txt (its current version is PRE-FIX) including all changed/added files and full evidence. Obtain final independent Sol general/Python review of bounded Decimal fix. Reviewer findings must be fixed/reverified. No tests/DB/modifying commands by reviewers.
4. Update final status, locally commit approved M5-01/02 files with explicit paths excluding scripts/pyproject.toml and uv.lock; merge --no-ff only after green/APPROVE. No push. Then proceed M5-03 broker point/loss-value capture and margin persistence under migration review, followed by API/worker and frontend per docs/api.md. Do not declare M5 complete yet.
5. Real-spec acceptance requires Borys's EURUSD/GBPUSD/XAUUSD/GER40 comparisons within one volume step; pending evidence does not prohibit synthetic development. Do not perform real-account operations or unauthorized live-AI/Whisper. Keep Monday M4 follow-ups pending, not falsely passed.

- 2026-11-08 owner update:100%; continue means work until instructed otherwise, no repeated usage-confirmation pauses. Full post-fix gate resumed with both URLs pinned to verified idle test DB.

- 2026-11-08 gate:1897backend+1skip passed, repeated unchanged DescribeVoice5000ms timeout (336frontend passed). Sol QA inspected real polling and kept all assertions, adding only documented per-test10000ms budget in frontend/src/features/describe/DescribeVoice.test.tsx. Targeted15voice tests passed; complete gate rerunning. This ninth changed file is part of required verification repair, no app behavior change.

- 2026-11-08 final post-fix full gate PASSED:1897backend+1intentional real-Whisper skip(121.12s),337frontend(23files,15.60s),all lint/type checks. Targeted sizing103tests/96%coverage; QA timeout repair15voice tests passed and full suite passed. Independent final reviews pending before commit.


## M5-01/02 completion - 2026-11-08

- Final independent Sol general and Python reviewers both APPROVE post-fix nine-file diff, no remaining substantive findings. Full make check passed1897backend+1intentional real-Whisper skip,337frontend; all lint/types. Sizing103targetedtests,96%coverage. RED and review-fix RED/GREEN evidence retained above.
- Local topic m5/calculator-plan, commit subject feat(calculator): add verified Decimal sizing core and M5 contract. Merge --no-ff only after this recorded green/APPROVE gate. No push. Original scripts manifests and QA data/worktrees preserved.
- Added per-test10s budget for recurring pre-existing voice test timeout after QA traced real polling+1.3s wait; assertions/app behavior unchanged. This is verification repair, not M5 product scope expansion.
- No calculator API/margin/schema/UI yet. Owner real-spec validation remains pending; M4 deferrals unchanged. Root sole runner, all core agents/reviewers completed.

### Historical resume note (before M5-03 completion)

M5-01/02 committed as `1cb42a7`, merged locally with `--no-ff` as `058406b`. Current topic is `m5/calculator-data` for M5-03. Sol backend owns metadata/model/migration and focused tests, initially tests only; root owns test execution and documentation. Observe RED before implementation, then full checks and independent database/general/Python review. Follow docs/api.md M5. Then API/worker, reusable UI and isolated QA. Continue authorizes work until owner says otherwise; do not repeatedly ask allowance. Never push or run real trading/AI/Whisper operations. Original untracked scripts manifests and QA resources remain preserved.

## M5-03 verification - 2026-11-09

- Resume found implementation beyond STATUS: nullable symbol_specs.point/tick_value_loss (captured from MT5 `point`/`trade_tick_value_loss`, never inferred), calculator_margin_samples and calculator_margin_requests tables (migration c8a41e62b903, downgrade tested), sync upsert of the new fields, tests in backend/tests/mt5/test_calculator_metadata.py and backend/tests/test_calculator_data.py. Signature computation, margin worker/dispatcher, order_calc_margin allow-list and API are NOT implemented (M5-04).
- Root retroactive RED against committed HEAD code (exported copy): 5 metadata tests failed, DB tests collection ImportError. GREEN focused 70 passed.
- Root fixes (no behaviour change): 12 ruff findings in new test/migration; test_bias_notes_downgrade_refuses_note_without_entries assumed bias migration was head, now asserts a refused downgrade leaves the revision unchanged.
- Docker Desktop was stopped; `make db-ensure` started it and also upgraded the DEV DB (trading_journal) to c8a41e62b903 (additive only, reversible with `alembic downgrade b6d41a9e2c57`). No data deleted.
- Full make check PASSED with both URLs pinned to local trading_journal_test, AI key empty: 1959 backend + 1 intentional skip (240.89 s), 337 frontend (23 files), all lint/type checks. Independent database/general/Python reviews next; no commit yet.
- Reviews: database-reviewer, code-reviewer and python-reviewer all APPROVE, no CRITICAL/HIGH. Applied post-review (tests/typing only): legacy_spec moved to tests/mt5/factories.py, named `_BEFORE_CALCULATOR` revision and guarded cleanup, DB refresh before final sync assertion, `_opt_dec -> Decimal | None`. PK/FK names verified in the test DB to follow the naming convention. Remaining notes recorded in DECISIONS.md 2026-11-09 (no range CHECK on point/tick_value_loss; request de-dup in API; worker DB clock and failure fields).
- Final full make check PASSED after fixes: 1959 backend + 1 intentional skip (208.36 s), 337 frontend, all lint/type checks; both URLs pinned to trading_journal_test, AI key empty.

### Historical resume note (before M5-04a)

M5-03 done on `m5/calculator-data`, merged locally into `main` with `--no-ff` (no push). Next: M5-04 on a new branch `m5/calculator-api` from `main`: `GET /api/accounts/{id}/symbol-specs`, `POST /api/calculator/calculate`, margin requests API, and the worker dispatcher with read-only `order_calc_margin` (allow-list change) per docs/api.md M5 and DECISIONS 2026-11-09. Tests first (tdd-guide for sizing/risk paths), root sole test runner, full gate with both DB URLs pinned to trading_journal_test and AI disabled, then independent reviews. The dev DB `trading_journal` is already at revision c8a41e62b903. Then M5-05 UI, M5-06 QA, M5-07 owner real-spec comparisons (still pending from Borys). Never push, no real trading/AI/Whisper operations. Keep scripts/pyproject.toml and scripts/uv.lock untracked and untouched.

## M5-04a and PM process rules - 2026-11-09

- PM accepted M5-03 and M4 (with open items). Process rules added to CLAUDE.md, AGENTS.md and DECISIONS: Codex only on `codex/<topic>`, never merges; session-start git check; pre-migration backup; Borys pushes main after every merge (orchestrator never pushes).
- Session-start check 2026-11-09: git matched STATUS; unexplained only `origin/m5/calculator-plan` on the remote (pushed by Borys, assumed) and the scripts manifests.
- scripts/pyproject.toml + scripts/uv.lock: empty PyCharm `uv init` project (created 2026-11-05 16:28, before scripts/.idea 16:30), not needed by the stdlib-only qa scripts: deleted and gitignored.
- M4 live AI eval: 10 calls exactly, 0.0860 USD, logged in logs/ai_usage.jsonl; 0 invented values, 0 questions; results in docs/reports/M4.md (which also records that M4-01..07 were Claude Code and M4-08/09 Codex).
- M5-04a: `python -m app.tools.migrate` (dev.py migrate step, make migrate). Backup only when migrations pending, non-`_test` DBs, host pg_dump else docker (local + compose port), failure aborts upgrade, unknown DB revision stops before dump, keep 10. Real run on dev DB: no migrations; real docker dump of trading_journal to a scratch folder is a valid archive (16 tables).
- QA DBs trading_journal_qa_m3 / qa_m4 kept; ask Borys before dropping.

## M5 extraction fixes (PM live-eval follow-up) - 2026-11-09

- Branch `m5/extraction-fixes` from main (d794465). PM fixes: bias confidence from UA/RU/EN number words (prompt list + test against extraction.yaml, "одиничка" added), bias key_levels several verbatim pieces joined by "; " (guard `key_levels_issue`, `find_phrase`), trade "тейк в точці B" → exit_reason `point_b`; zone+price = one level (prompt). CLAUDE.md push line per PM. DECISIONS/api.md/M4 report updated.
- Live re-run done (PM-authorized, exactly 3 calls, 0.0280 USD, logs/ai_usage.jsonl). Zone+price prompt fix verified live with 1 extra call authorized by Borys (0.0076 USD, MATCH, docs/reports/M4.md).
- 2026-11-09 evening: laptop lost power during the full make check (uncommitted). Resumed: full make check PASSED (2008 backend + 1 intentional skip, 337 frontend, all lint/types; both DB URLs pinned to trading_journal_test, AI key empty). code-reviewer APPROVE (no CRITICAL/HIGH/MEDIUM); LOW fixes: 3 more key_levels edge tests (focused 91 passed), report heading; punctuation-only piece → BACKLOG. Committed and merged --no-ff into main.

### RESUME FROM HERE

2026-11-12: M5 merged (2f48604). M6 planned (M6-01, contract docs/api.md "## M6"). M6-02: tests committed RED (5861fa0) on m6/digest-metrics, backend-dev implementing app/domain/digest_metrics.py; then make check, code-reviewer + python-reviewer, merge.

2026-11-12: M5 ACCEPTED by PM (all 4 symbols). Login 11459118 = «FN Stellar Funded» (closed; both funded accounts in the app). M5-12 closing report + real-spec tests on m5/close-report. NEXT: merge, then M6 dashboard and digests (PRD 6.7, 6.10): all % of account size, canonical symbol names.

2026-11-11 evening: M5-10 risk base started on m5/risk-base. GER30 live check still pending: app not running since migration (last sync 18:53 UTC, fx_rates empty). Account 11459118 answer came as an unfilled template: ask again.
M5-10 DONE and merged. Dev DB migrated 2026-11-11 23:23 UTC to a3e7c91d5b20 (backup backups/pre-migration-a3e7c91d5b20-20261111T232329Z.dump): account 12109877 size 10000.00, 14 trades percents recomputed from it (e.g. trade 4 risk 1.0304 %). Rule violations recompute at first worker start. NEXT: Borys starts app -> after first sync read fx_rates + GER30 mt5_loss_per_tick (~0.11091 expected) -> Borys rechecks GER40 (budget 100.00, lot 0.13). Account 11459118 answer still pending.

2026-11-11: M5-07 GER40 FAIL (cross-currency tick value). Started M5-09 on m5/fx-conversion, contract in api.md. App has ONE account: id 1 login 12109877 FN Stellar Lite 2-Step, balance 10401.70 synced 2026-11-11 15:54 UTC (login 11459118 not in the app). "Risk-base change (account size)" not found in docs: ask Borys/PM.
M5-09 DONE: tdd-guide RED, backend part A/B + review fix batch, frontend; full make check green (2684 backend + 1 skip, 406 frontend; both DB URLs pinned to trading_journal_test via %TEMP%/m509_gate.py since make check runs db-ensure). Reviews all APPROVE. Merged to main. Dev DB migrated 2026-11-11 19:24 UTC to f6ea0d1af419 (backup backups/pre-migration-f6ea0d1af419-20261111T192357Z.dump; 14 trades, 4 specs intact, fx_rates empty until first sync). NEXT: Borys starts the app -> after first sync read symbol_specs.mt5_loss_per_tick for GER30 and fx_rates (expect ~0.11091; if ~0.12 take to PM) -> Borys rechecks GER40 (expect 0.14 at budget 104.02). Then risk-base question.


`m5/extraction-fixes` merged into main (480d87d). M5-04b done and merged into main (8abb42e). Dev DB trading_journal upgraded to 80ae699b47ce via `make migrate`; backup backups/pre-migration-80ae699b47ce-20261109T220228Z.dump. M5-04c DONE and merged into main (0a99bfc). M5-04d DONE and merged into main (4918509, M5-04 complete). M5-05 DONE and merged into main (2940293). M5-06 DONE and merged. M5-07 in progress: Borys item 2 (2026-11-10): EURUSD/GBPUSD/XAUUSD OK; GER40 shows «(потрібна синхронізація)» because FundedNext names it GER30. Borys's fix request = new task M5-08 canonical symbol aliases (config/symbols.yaml canonical → broker names per account/firm; spec/trade sync + calculator resolve; data migration for stored GER30 with pre-migration backup; bias alignment; calculator shows "GER40 (GER30)"; «символ не знайдено у брокера: GER40»; fixture test with GER30; DECISIONS). Investigation done: dev DB has stale spec GER30 (point NULL, synced 2026-11-06; watch prefix GER40 never matched) and 4 trades GER30; no bias entries; margin requests EURUSD only. Contract in docs/api.md "M5-08 Canonical symbols" + DECISIONS (commit a9ae220 on branch m5/canonical-symbols). Frontend part done (398 frontend tests, uncommitted). Backend phase 1 tests written (new: test_symbols_config, domain/test_symbols, test_canonical_symbols, test_calculator_symbols, test_symbol_migration, fixture funded_next_ger30.json, config/symbols.yaml); root observed RED (collection/import errors); backend-dev phase 2 implemented; first full check 7 failed (SQLAlchemy .tuples() deprecation + test helper), fixed; full make check PASSED (2452 backend + 1 skip, 398 frontend); coverage symbols 93–100%. Reviews: database-reviewer APPROVE, code-reviewer APPROVE, python-reviewer CHANGES REQUESTED (stale recompute on broken bias/rules config, services→api import, invisible apply failure; + bias⊆symbols runtime check, set-based updates, tests decoupled from real symbols.yaml, missing=[] before first sync). fix batch applied (both agents), full make check PASSED (2473 backend + 1 skip, 398 frontend), python-reviewer re-review APPROVE; MERGED into main. Remaining: `make migrate` on dev DB (needs Borys's app stopped first), restart, Borys continues M5-07 GER40. Old: root marked QA evidence superseded + BACKLOG. Then make check, python-reviewer re-review, merge, `make migrate` dev DB, restart app, Borys continues M5-07 GER40. Original plan: backend-dev phase 1 tests (symbols.yaml loader/resolver, migration broker_symbol/canonical_symbol, re-apply step, GER30 fixture sync, bias, calculator/margin, journal/trade_check); frontend-dev calculator labels "GER40 (GER30)" + «символ не знайдено у брокера». Then RED, implement, make check, database-reviewer + code-reviewer + python-reviewer, merge, `make migrate` on dev DB (backup), then Borys continues M5-07 for GER40. History of M5-06: qa-tester built scripts/qa_live_check_m5.py (+ M4 helper refactor), 61 guard tests, synthetic fixture calculator_qa.json, HTTP evidence (all 4 symbols match hand calcs; live margin, de-dup, estimate, unavailable, errors, worker-stopped) and docs/reports/M5-live-check.md. QA DB trading_journal_qa_m5 created (backup backups/pre-migration-80ae699b47ce-20261110T074542Z.dump) and kept. Root browser check in Chrome PASSED (page, live margin, unavailable, below_min_volume, Home panel, no console errors); QA app stopped. Full make check PASSED (2316 backend + 1 skip, 392 frontend). code-reviewer + python-reviewer running; then commit/merge, then M5-07 = Borys's real comparisons + docs/reports/M5.md. Plan: own QA DB `trading_journal_qa_m5` + TEMP config/data, fixture MT5 with point/tick_value_loss/margins for EURUSD/GBPUSD/XAUUSD/GER40-like symbols (labelled synthetic), worker running, browser check of the page + Home panel (calculate, margin live via fixture, estimate, unavailable, errors), full regression; no real MT5/AI/Whisper. Then M5-07 owner comparisons + docs/reports/M5.md. History of M5-05: frontend-dev built features/calculator (shared form for page + compact Home panel, margin polling max 75 polls, all error codes in uk.ts, only active accounts); 381 frontend tests (+44). Full make check PASSED (2255 backend + 1 skip, 381 frontend), production build OK; api.md: off_tick_grid fields list + pending-without-worker note. code-reviewer CHANGES REQUESTED (HIGH: generic error toast on every calculate error; MEDIUM: failed margin hides error_code, missing superseded-calculate test; LOWs); frontend-dev fixing; then make check, re-review, commit/merge. Browser check moved to M5-06 isolated QA (needs a QA DB + fixture with point/tick_value_loss/margins). History of M5-04d: exact shapes in docs/api.md "M5-04d exact shapes"; backend-dev phase 1 wrote tests (tests/mt5/test_real_margin.py, test_fixture_margin.py, test_guard.py, test_worker.py, tests/test_margin_requests_api.py, tests/test_margin_job.py); root observed RED (83 failed / 105 passed + margin_job ImportError); backend-dev phase 2 implemented (services/margin_requests.py, worker/margin_job.py, worker/mt5_shared.py, calc_margin real+fixture, sync lock). GREEN 344 focused, coverage 96–100%; full make check PASSED (2235 backend + 1 skip, 337 frontend). code-reviewer + python-reviewer both APPROVE (MEDIUM: stuck processing rows + de-dup, silent finish rowcount 0, untested storable guard; LOWs); backend-dev applied fixes (STALE_PROCESSING_S 261 s sweep + de-dup bound, finish warnings, check_storable tests, LOWs); root fixed a test setup bug; 364 related passed, full make check PASSED (2255 backend + 1 skip, 337 frontend); code-reviewer confirming the fix batch; then root checks, code-reviewer + python-reviewer. History of M5-04c: exact shapes/error codes added to docs/api.md + DECISIONS; tdd-guide wrote tests (core PositionSizeError codes + tests/test_calculator_api.py, 76 cases); root observed RED (domain ImportError; API 74 failed / 2 passed = 404 tests passing only because routes are missing, recheck after GREEN); backend-dev implemented (api/calculator.py, schemas/calculator.py, services/calculator.py, PositionSizeError in core). GREEN: 207 focused passed, coverage core 97% / service 98%; full make check PASSED (2099 backend + 1 skip, 337 frontend). code-reviewer APPROVE (4 LOW); python-reviewer CHANGES REQUESTED (HIGH: NUL/lone-surrogate symbol → 500; MEDIUM: margin product at 28-digit context, validation_error without details.fields, _result params, validator typing). backend-dev applied all fixes test-first (test_calculator_api.py was accidentally emptied and rebuilt; root verified by AST vs the original: 64/64 items identical, 1 strengthened, 11 added). Focused 232 passed, coverage 97/100/100%; full make check PASSED (2124 backend + 1 skip, 337 frontend). python-reviewer re-review running; then commit, merge. Then M5-04d (margin requests API + worker + order_calc_margin). Next:
M5-04a merged into `main` locally (Borys pushes). Next M5-04b on branch `m5/calculator-api` from main: migration dropping `calculator_margin_samples` and the `signature` columns (database-reviewer); the dev DB upgrade will go through the new backup. Then M5-04c (tdd-guide tests first: specs list + calculate with cached estimate, never MT5) and M5-04d (margin requests API, 2 s worker job under the sync lock, read-only order_calc_margin, fixture source). Then M5-05 UI with the owner checklist (4 symbols, exact Ukrainian UI names and MT5 menu paths), M5-06 QA, M5-07 owner comparisons. Never push; no real trading; no further live AI without authorization.

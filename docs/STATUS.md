# STATUS

Current milestone: **M4 Bias** (started 2026-11-05). M3 accepted 2026-11-05, M2 accepted 2026-11-04, M1 accepted 2026-11-03, M0 accepted 2026-11-01.

## Environment notes (dev laptop)
- Python 3.12.9, Node 24, npm 10, Docker Desktop 29, git.
- Installed for this project: `uv` 0.13.1 (`pip install --user uv`), GNU make 4.4.1 (`winget install ezwinports.make`).
- No native Postgres; DB runs in Docker (`docker compose up -d db`).

## Where we stopped / how to resume (updated continuously)
Last update: 2026-11-06 (M4-09 complete: full verification, actual launcher smoke and independent general/Python APPROVE. M4-08 already committed/merged. Owner allowance reading 55%; M4-10 remains owner-only.)
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

### RESUME FROM HERE

1. **Stop before M4-10 owner acceptance.** M4-09 implementation, full verification, launcher smoke and independent reviews are complete. Borys should use docs/reports/M4-live-check.md; do not repeat completed M4-08/M4-09 work.
2. Preserve QA DB/audio, original untracked scripts manifests and worktrees. Do not rerun seed creation or repeat Whisper/live AI.
3. Stop before M4-10; Borys executes docs/reports/M4-live-check.md and provides owner/PM acceptance. No push.

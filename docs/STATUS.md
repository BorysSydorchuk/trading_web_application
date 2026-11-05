# STATUS

Current milestone: **M4 Bias** (started 2026-11-05). M3 accepted 2026-11-05, M2 accepted 2026-11-04, M1 accepted 2026-11-03, M0 accepted 2026-11-01.

## Environment notes (dev laptop)
- Python 3.12.9, Node 24, npm 10, Docker Desktop 29, git.
- Installed for this project: `uv` 0.13.1 (`pip install --user uv`), GNU make 4.4.1 (`winget install ezwinports.make`).
- No native Postgres; DB runs in Docker (`docker compose up -d db`).

## Where we stopped / how to resume (updated continuously)
Last update: 2026-11-05 (M3 accepted; M4 planned: contract in docs/api.md "## M4", tasks below; M4-02 started).
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
- [ ] M4-02 M3 follow-ups: AI warm-up by time (start if last successful AI call > 20 h, Mon–Fri 07:30 Brussels) + prompt rule "Сетап H4, H1 Flow" → setup_context yes, with fixture (backend-dev) — branch m4/m3-followups
- [ ] M4-03 Bias DB + config: `bias_notes` table, bias_entries.bias_note_id, audio_notes.bias_entry_id → bias_note_id, `config/bias.yaml` loader, `GET /api/bias/config` (backend-dev, database-reviewer) — branch m4/bias-schema
- [ ] M4-04 Bias alignment domain (pure) + recompute service for trades on note create/edit/delete and on sync (backend-dev) — branch m4/bias-alignment
- [ ] M4-05 Bias API: notes CRUD, by-period, result marking, bias audio upload, status/reminders (backend-dev) — branch m4/bias-api
- [ ] M4-06 Bias extraction: prompt, per-symbol schema, guards, fixtures (UA/RU/EN, aliases) (backend-dev) — branch m4/bias-extraction
- [ ] M4-07 Bias page: list, note form (kind, date, recorder + audio file, text, "Заповнити з тексту", per-symbol cards, links), "біас був правильний" marking (frontend-dev) — branch m4/bias-ui
- [ ] M4-08 Головна bias status + reminders, sidebar badge; alignment daily/weekly/monthly in Journal + Describe (frontend-dev) — branch m4/bias-dashboard
- [ ] M4-09 QA (fixtures, AC: daily + weekly entries, trade alignment, pre_ny reminder after 12:30; ≤ 3 Whisper runs) + docs/reports/M4-live-check.md + scripts/qa_live_check_m4.py (qa-tester, orchestrator)
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

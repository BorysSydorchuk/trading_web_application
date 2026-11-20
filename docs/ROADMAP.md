# ROADMAP

Each milestone ends with a report in `docs/reports/M<n>.md` and a stop for PM review.
Acceptance criteria (AC) must be verified by running the app, not only by tests.

## M0. Foundation
- Monorepo: `backend/` (FastAPI, uv), `frontend/` (Vite React TS), `worker/` (or `backend/worker`), `config/`, `docs/`, `logs/`.
- `.env.example`, settings via pydantic-settings, `.gitignore` (env, logs, audio, backups).
- PostgreSQL connection, Alembic set up, full schema from PRD 6.1 to 6.9 as first migration (accounts, symbol_specs, trades, trade_exit_deals, chart_links, audio_notes, bias_entries, digests, rule_violations, sync_log).
- `make check` (ruff, mypy, pytest, eslint, tsc), `make dev`, `start.bat`.
- Frontend shell: sidebar navigation (Головна, Потрібен опис, Журнал, Біас, Дайджести, Калькулятор, Налаштування), dark theme, i18n file `uk.ts`, global error toast, API client.
- Health endpoint + status bar showing backend/DB status.

AC: fresh clone on Windows → follow README → `start.bat` opens the UI in the browser with all empty pages, status bar green. `make check` passes.

## M1. MT5 sync and trade data
- Accounts CRUD (Settings page).
- Worker per PRD 6.2: portable terminals, sequential accounts, deals → trades by position_id, partial closes, initial SL capture, symbol specs sync, server time offset detection (6.3), session classification.
- Computed fields: risk %, R, planned RR, P&L %, session, re-entry flag.
- Rules engine v1 (PRD 6.9) attaching violations.
- `config/journal_fields.yaml` driven field definitions + JSONB `extra` (PRD 6.4).
- Sync status per account visible in UI; errors visible.
- Journal page: table of trades with filters (account, symbol, period, status), sortable, column chooser.
- Mock MT5 source (fixtures from recorded deals) so everything is testable without a terminal.

AC: with Borys's real account, last 30 days of trades appear correctly (he checks 5 trades against MT5 history: prices, P&L, R). Closing a demo trade shows it in "Потрібен опис" within 2 minutes. Closing the terminal shows an error in the status bar, app keeps running. Unit tests for trade building, R, time conversion incl. DST, rules.

## M2. Describe a trade (text + links)
- Describe screen per PRD 6.5 with text input and chart links (validate TradingView URLs, store, show thumbnail/preview link).
- Claude extraction from text into the schema with strict JSON, glossary in the system prompt, prompt stored in `backend/prompts/`.
- Form with AI-filled markers, required-field validation, draft vs complete.
- Status flow needs_sl → needs_description → draft → complete.

AC: Borys describes 3 real trades by text in under 2 minutes each, AI fills most fields correctly, never asks questions, missing fields highlighted. Extraction tested with 10 sample texts (fixtures) including mixed Ukrainian/Russian/English terms.

## M3. Voice input
- Hold-to-record in browser, upload, local faster-whisper transcription (worker queue, progress in UI), transcript editable, then same extraction as M2.
- Audio files stored in `data/audio/`, linked to trade or bias entry.

AC: a 2-minute voice note is transcribed and fields prefilled in under 30 s (report actual timing on Borys's laptop). Failure of transcription shows a clear error and keeps the audio.

## M4. Bias
- Bias entries per PRD 6.6 (pre_london, pre_ny, weekly, monthly), voice or text, per symbol.
- Dashboard reminders for missing bias.
- bias_alignment computed per trade (daily, weekly, monthly) and shown in journal and describe screen.
- Manual "bias was right" marking after the session.

AC: create both daily entries and a weekly entry; a trade in that session shows the correct alignment; missing pre_ny bias after 12:30 shows a reminder.

## M5. Position calculator
- PRD 6.8 calculator page, also reachable as a compact panel from the dashboard.
- Unit tests with real FundedNext specs for EURUSD, GBPUSD, XAUUSD, GER40.

AC: Borys checks 4 calculations (one per symbol) against MT5's own margin/risk and they match within one volume step.

## M6. Dashboard and digests
- Dashboard per PRD 6.10 with limits banner.
- Weekly and monthly digests per PRD 6.7: metrics, breakdowns, charts, deviation highlighting vs norm, review form, next-period bias, optional AI summary.
- Saved digests list.

AC: digest for a week with real trades matches hand-calculated win rate, total R and P&L. Deviations highlighted. Review + next week's bias saved from one screen.

## M7. Hardening — technical milestone CLOSED

- Owner/PM decision, 2026-11-16: M7-01 through M7-07 fully ACCEPTED; the M7 technical milestone is CLOSED. Daily pg_dump backups, log rotation, startup checks, performance, installation documentation, security and integrated QA are accepted.
- M7-08 preparation ACCEPTED; the previous M7-08 live-acceptance plan is **SUPERSEDED**. Actual five-day live validation remains **0/5**, has not passed, and is transferred to M8. Technical closure follows the explicit owner/PM decision, not a claim of five successful live days.
- Preserve `m7/trading-week` at `8b6ade5` and its `docs/reports/M7-08.md` daily checklist. Do not merge or delete that branch/commit. The template is stored on that branch, not in main; view it from repository-root PowerShell with `git show 8b6ade5:docs/reports/M7-08.md`. Its historical closure conditions are superseded by this decision.

## M8. UX & Functional Improvements — technically complete (2026-11-20), waiting for the PM

- Scope came from owner feedback in normal use: `docs/M8_BACKLOG.md` (M8-01..M8-17 plus the PM's tier S starting-balance suggestion).
- **Accepted:** M8-11, M8-01, M8-16, M8-04..08, M8-10a, M8-10b, M8-10c and the starting-balance suggestion.
- **Technically accepted or merged, owner check open:** M8-09, M8-01b, M8-02 + M8-03, M8-15, M8-12, M8-13, M8-14.
- **Summary:** `docs/reports/M8.md`.
- **Owner decisions pending:** AI prefill of manual violations (YES / NO); native PostgreSQL instead of Docker (not authorized).
- **Live validation from M7:** 0/5, not run in M8.
- The previous M8 placeholder for optional Notion export (PRD 6.11) stays superseded and deferred.

## Backlog
New ideas from Borys or agents go to `docs/BACKLOG.md`. PM decides when they enter a milestone.

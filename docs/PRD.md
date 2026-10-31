# PRD: Trading Journal (working name)

Version 1.0, 31 Oct 2026. Owner: Borys. PM: Claude (chat).

## 1. Problem
Borys trades FundedNext 2-step prop challenges on MT5. The previous tool (a Python MT5 to Notion sync script) was unreliable: frequent errors, lag, poorly thought-out flows, and an AI assistant that kept re-asking him about decisions. He needs one local app that captures every trade with full context, links trades to his plan (bias), and turns this into weekly and monthly reviews.

## 2. Goals
1. Every closed trade on every account appears automatically, and Borys is prompted to describe it.
2. Describing a trade takes under 2 minutes: voice or text, chart links attached, AI fills the structured fields, Borys only confirms or corrects.
3. Every trade row is complete (no empty required columns), so analytics are trustworthy.
4. Bias (expectations) is recorded twice per trading day plus weekly and monthly, and each trade is scored against it.
5. Weekly and monthly digests show performance clearly and highlight deviations from his norm.
6. Accurate position sizing for any symbol on any account (GER40, XAUUSD especially).
7. Stable: no crashes, no silent failures, fast UI.

## 3. Non-goals (v1)
- No trade execution, no copy trading.
- No cloud deployment, no multi-user, no auth beyond localhost.
- No Telegram bot (replaced by the app UI).
- Notion is an optional one-way export in a late milestone, never the main store.

## 4. User and context
- Single user, Windows laptop, MT5 terminals (FundedNext), Europe/Brussels time.
- Trades EURUSD, GBPUSD, XAUUSD, GER40; may test new symbols.
- Trading hours 08:00 to 16:00 Brussels: London 08:00 to 11:00, pre-market (break, no entries) 11:00 to 13:00, NY 13:00 to 16:00. Entries only during London and NY.
- Draws charts in TradingView and shares snapshot links (`https://www.tradingview.com/x/...`).
- UI language: Ukrainian.

## 5. Tech stack (fixed)
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, `uv` for dependencies.
- DB: PostgreSQL 16 (native Windows install or Docker; support both via `DATABASE_URL`). Tests use a throwaway Postgres DB (or testcontainers).
- MT5: official `MetaTrader5` Python package, read-only.
- Background jobs: separate worker process (APScheduler) for MT5 sync. Not inside the API process.
- Speech to text: local `faster-whisper` (model `small` or `medium`, language `uk`, fallback auto-detect since Borys mixes Ukrainian, Russian and English trading terms). Runs locally, free.
- AI: Anthropic Claude API (`anthropic` SDK) for structured extraction and digest summaries. Budget about 5 to 7 USD per month. Use a mid-tier model for extraction, configurable in `.env`.
- Frontend: React + TypeScript + Vite, TanStack Query, Tailwind CSS + shadcn/ui, Recharts (or lightweight-charts for equity curve). Dark theme default.
- Start everything with one command: `start.bat` (Windows) and `make dev`.
- Architecture: storage behind repository interfaces; exporters (Notion) as pluggable adapters.

## 6. Features

### 6.1 Accounts
- Fields: name, firm, program (e.g. Stellar 2-Step), phase (Phase 1 / Phase 2 / Funded), login, server, terminal path, starting balance, currency, status (active / passed / failed / archived), firm rules (daily loss %, max drawdown %, profit target %).
- CRUD in Settings. Secrets (investor password) stored in `.env` or an encrypted local secrets file, referenced by account.

### 6.2 MT5 sync (worker)
- The MT5 Python package talks to one terminal per process. Use **one portable terminal folder per account** (`terminal64.exe /portable`), and the worker iterates accounts sequentially (initialize, read, shutdown). Document setup in README.
- Every 60 s during trading hours, every 15 min otherwise: pull deals and orders history, open positions, account info.
- Build trades from deals by `position_id` (handle partial closes: one trade, multiple exit deals).
- Capture **initial stop loss**: from the opening order / first SL seen on the open position. If unavailable, trade status gets `needs_sl` and the UI asks for it (required for R).
- Sync symbol specifications per account (contract size, tick size, tick value, volume min/step/max, digits, currency) into `symbol_specs`.
- Idempotent (upsert by account + position_id). Resilient: if a terminal is closed or login fails, log it, show it in the UI status bar, retry next cycle, do not crash.
- New closed trade → status `needs_description` → appears in the "Потрібен опис" inbox with a badge counter and a browser notification.

### 6.3 Time handling
- Store UTC. MT5 timestamps are broker server time; detect offset per account (compare `symbol_info_tick().time` with UTC now, round to whole hours) and convert. Unit-test DST transitions (late March, late October).
- Session classification by Brussels time: `london` 08:00 to 11:00, `premarket` 11:00 to 13:00, `ny` 13:00 to 16:00, else `outside`. Allowed entry windows: london and ny only. Session boundaries live in `config/rules.yaml`, not in code.

### 6.4 Trade record (all columns)
Auto (from MT5): account, symbol, direction, open/close time (UTC), duration, entry/exit price (volume-weighted), volume, initial SL, TP, commission, swap, gross/net P&L, P&L % of balance, risk amount, risk % (from initial SL), R multiple, planned RR (TP vs SL), session, weekday, hour, re-entry flag (same symbol + direction within the same session after a loss).

**Journal fields will change over time** (Borys will revise them). Design for it:
- Field definitions (key, Ukrainian label, type, options, required, used in analytics) live in `config/journal_fields.yaml`. The form, the AI extraction schema and digest breakdowns are generated from this file.
- Stable analytic fields below are real columns. New or experimental fields go into a JSONB `extra` column first; promoting one to a real column is a normal Alembic migration with data copy.
- Changing options of an enum field must not break old trades (keep old values, mark them deprecated).

Journal (from description, AI-prefilled, user-confirmed). Initial set, **required** unless marked optional:
- `setup_context`: Flow H1 synced with H4: yes / no / partially
- `poi_type`: FVG H4 / FVG H1 / other (text)
- `fvg_kind`: fractal-updating / post-manipulation / n.a.
- `entry_model`: IFVG M5 / QM M5 / other
- `exit_reason`: fractal update / point B target / SL / TP / manual / other
- `bias_alignment`: auto-computed (see 6.6), user can override with reason
- `followed_plan`: yes / no
- `rule_violations`: auto-detected list (see 6.9) plus user-added
- `emotion_before`, `emotion_after`: separate columns, enum (спокій, впевненість, FOMO, страх, реванш, втома, нудьга) plus optional text
- `mistakes` (optional text), `lesson` (optional text)
- `quality_rating`: 1 to 5 (setup quality, independent of result)
- `chart_links`: at least 1 TradingView link (before entry), optional after-trade link
- `raw_text` / `audio_file` / `transcript`: kept for history
- `status`: needs_sl → needs_description → draft → complete

### 6.5 Describe a trade (core flow)
1. Inbox shows trades needing description. Click one → Describe screen with auto data on the left.
2. Input: hold-to-record button (browser MediaRecorder, webm/opus) and/or a text box, plus a field to paste one or more chart links.
3. Backend: save audio file → transcribe → Claude extracts fields into the schema (strict JSON / tool use) → form on the right is prefilled. Fields filled by AI are marked.
4. Borys edits anything inline and presses "Зберегти". Missing required fields are highlighted in red; save as draft is allowed, complete is not.
5. **AI behaviour rules (important, past pain point):**
   - Never ask about or challenge his decisions while he describes a trade.
   - Never ask follow-up questions in a chat loop. If a required field is missing, leave it empty and highlighted. Optionally show one line "Не вистачає: …".
   - Never invent values. Unknown means empty.
   - The system prompt includes his strategy glossary (FVG, IFVG, QM, POI, Flow, fractal, point B) so transcripts in mixed language map correctly.
6. Target: transcription + extraction under 30 s for a 2-minute voice note on his laptop. Show progress.

### 6.6 Bias (expectations)
- Entry types: `pre_london` (before 08:00), `pre_ny` (during pre-market 11:00 to 13:00), `weekly` (weekend or Monday morning), `monthly` (first days of month).
- Per entry, per symbol: direction (bullish / bearish / neutral / no trade), key levels / POI (text), narrative, chart links, confidence 1 to 3. Input by voice or text with the same extraction flow.
- Dashboard reminder if pre_london is missing at 07:45, or pre_ny is missing at 12:30.
- `bias_alignment` per trade: compare trade direction with the latest daily bias for that symbol and session: aligned / counter / neutral-bias / no bias. Also store alignment with weekly and monthly bias.
- Bias accuracy: after the session, Borys marks (or the system estimates from the session's price move via MT5 rates) whether the bias was right. Used in digests.

### 6.7 Weekly and monthly digest
- Generated on demand and suggested automatically (Friday after 16:00 for weekly, last trading day for monthly).
- Metrics: trades count, net P&L (money and %), total R, win rate, average win R, average loss R, expectancy R, profit factor, max drawdown within period, best/worst trade.
- Breakdowns: by symbol, session, hour, weekday, entry model, POI type, bias alignment, followed plan vs not, emotion.
- Rule section: violations count and their P&L cost.
- Bias section: bias accuracy, P&L of aligned vs counter trades.
- **Deviation highlighting:** compare period metrics with his norm (rolling last 60 trading days, or all history if fewer). Values worse than norm by more than 1 standard deviation (or a configurable threshold) highlighted red, better highlighted green.
- Charts: equity curve (per account and combined), R distribution, P&L by hour heatmap.
- Review form: what worked, what to fix, focus for next period. Then the weekly/monthly bias entry for the next period from the same screen.
- Optional AI summary (one button): short factual observations from the numbers and journal text. No moralising, no generic advice.
- Export digest to Markdown/PDF (later).

### 6.8 Position size calculator
- Inputs: account (dropdown), symbol (from that account's `symbol_specs`), direction, entry price, SL price (or SL distance in points), risk % (default 1.0) or risk amount.
- Output: lot size rounded **down** to volume step, real risk in money and % after rounding, margin required (via `order_calc_margin` when the terminal is reachable, else estimate), TP prices for RR 1.5 / 2 / 3.
- Uses current account balance (or the firm's reference balance, configurable per account).
- Works offline with last synced specs; shows the specs date.
- Must be correct for GER40 and XAUUSD on FundedNext: unit tests with real spec values Borys will provide from the terminal.

### 6.9 Rules engine
Configured in `config/rules.yaml`, editable later in Settings:
- risk per trade 1% (flag if actual risk % > 1.1)
- daily stop: −3% / +5%; weekly stop: −6% / +10%
- max 10 trades per week; max 1 re-entry per idea
- min planned RR 1.5
- entries only in london (08:00 to 11:00) or ny (13:00 to 16:00) sessions; entries in premarket or outside are violations
- QM entry model not in NY session
- no breakeven moves (detect SL moved to entry)
Violations auto-attached to the trade. Dashboard shows today's and this week's P&L vs these limits with a clear "СТОП на сьогодні" banner when hit.

### 6.10 Dashboard (home)
Today: bias status for both sessions, P&L today/week vs limits, inbox count, open positions, sync status per account (last sync time, errors). Quick links to calculator and describe.

### 6.11 Notion export (late milestone, optional)
One-way push of complete trades and digests into existing Notion databases via an adapter. Rate-limited queue, retries, never blocks the app.

## 7. Non-functional
- Startup to usable UI under 10 s. Pages load under 300 ms on local data.
- No unhandled exceptions reach the user as blank screens; error toasts with readable Ukrainian text, details in `logs/`.
- Daily automatic DB backup (`pg_dump`) to a configurable folder, keep 14.
- Test coverage focus: trade building from deals, R and risk calc, time conversion, rules engine, calculator, digest metrics.

## 8. Open items (PM will resolve, do not block on them)
- Exact FundedNext symbol specs for GER40/XAUUSD (Borys provides from terminal).
- Whether bias accuracy is manual or auto-estimated by default (implement manual first).
- Final app name.

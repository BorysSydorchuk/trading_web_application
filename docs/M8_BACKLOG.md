# M8 backlog — UX & Functional Improvements

Source: PM review 2026-11-16 (owner feedback from normal use) and section 5 of the PM handoff `docs/handoff/PM_HANDOFF_2026-11-16.md` (owner dictation 2026-11-16, filled in 2026-11-18). Each item needs a separate PM go before implementation.
Order (owner/PM): M8-11 -> M8-09 -> M8-01 -> M8-02 + M8-03 -> M8-04..M8-08 (one taxonomy batch, one migration) -> M8-10 (after the owner picks a design direction).
Five real live-validation days transferred from M7: **0/5**.

Owner wording below is copied from handoff §5 (labels in «» are the owner's Ukrainian wording). «PM proposal» marks handoff details that are a PM design proposal, not owner intent. «Decision» marks owner/PM decisions already recorded in `docs/DECISIONS.md` (2026-11-16).

## Summary

| ID | Topic | Priority | Tier | Depends on | Status |
|----|-------|----------|------|------------|--------|
| M8-01 | Exclude a trade from strategy statistics | 3rd (HIGH) | L | M8-09 | accepted (owner PASS, PM 2026-11-18) |
| M8-02 | Describe an OPEN trade, complete it after close | 4th (HIGH) | L | M8-01 | merged `5a05b6a`, TECHNICAL ACCEPTED (PM 2026-11-18), owner check pending |
| M8-01b | Auto-recompute saved digests on exclude/include | after M8-02 | L (migration) | M8-01 | merged `71e599b` 2026-11-18, owner check + PM review pending |
| M8-12 | Run without visible windows: tray, autostart, shortcuts, hidden MT5 terminals | 1st of batch | M | — | merged `1d7b765` 2026-11-18, owner check pending |
| M8-16 | MAE / MFE per trade in R | 2nd of batch | L | M8-12 | authorized 2026-11-18, in progress |
| M8-13 | Choose the Claude model per call type | 3rd of batch | M | — | authorized 2026-11-18, planned |
| M8-14 | Charts on «Головна» | 4th of batch | M | — | authorized 2026-11-18, planned |
| M8-15 | «Головна» lists «Потрібен опис» with «Описати»; Journal filter open with/without description | after M8-01b | S/M | M8-02 | TECHNICAL ACCEPTED (PM 2026-11-18), merged `860b4c8` 2026-11-18, owner check pending |
| M8-03 | Before/after chart link defaults | 4th (with M8-02) | L (with M8-02, no migration) | M8-02 | merged `5a05b6a`, TECHNICAL ACCEPTED (PM 2026-11-18), owner check pending |
| M8-04 | Rule violation taxonomy | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-05 | Independent H1 / H4 context | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-06 | Multi-select POI, Fractal H1/H4 | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-07 | Multi-select, conditional FVG type | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-08 | Entry model single-select, «Інше» needs text | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-09 | Exit reason from MT5 | 2nd | L | M8-11 | merged `eb6e690`, TECHNICAL ACCEPTED, owner check pending (next 3 closed trades) |
| M8-10 | UI/UX research, redesign, branding | last | TBD | owner design choice | planned (research only) |
| M8-11 | Footer overscroll | 1st | S | — | accepted (owner PASS, PM 2026-11-17) |

## M8-01 — Exclude specific trades from strategy statistics (HIGH)

Status 2026-11-18: merged `69b3239`, dev DB at e4a7c2f9b315, report `docs/reports/M8-01.md`. Owner check PASS, PM ACCEPTED 2026-11-18.

### M8-01b — Saved digests follow exclude/include (PM answer 2026-11-18)
- Excluding or returning a trade updates the affected saved digests automatically: the week and the month containing the trade, per account and combined. Numbers only are recomputed; saved review text is never touched.
- A saved AI summary is NOT re-run; it gets the badge «Підсумок застарів: дані змінено <date>» until the owner presses «Оновити підсумок».
- Tier S/M, may go with M8-02.

- **Owner wording:** a gold/XAUUSD trade opened on the 11th only to check whether a newly funded account could trade; it should not distort strategy/performance statistics or require a normal strategy journal description. Per-trade action «Не враховувати у статистиці» with a **mandatory written reason**. Owner should be able to identify/read the excluded trade later.
- **Decision:** excluded trade leaves strategy statistics (win rate, R, expectancy, breakdowns, digests, «Потрібен опис») but stays in all real-money/risk numbers (account P&L, balances, daily/weekly stops, 10 trades/week limit, risk rule checks). Reversible, mandatory reason, raw MT5 data never changed, survives re-sync.
- **PM authorization 2026-11-18 (scope):** action in the Journal row menu and on the Describe screen; reversible via «Повернути у статистику»; history of both actions (when, reason). Strategy side also covers profit factor, all breakdowns (setup, POI, sessions, emotions…), bias accuracy/alignment stats, digest strategy metrics, the 60-day norm, the inbox and its badge. Money side also covers Home today/week P&L, «СТОП» banners, risk rule checks (1 %, daily/weekly stops), account drawdown. Digests show a block «Виключені угоди: N, P&L X USD» (symbol, date, reason) so totals reconcile. Journal: badge «виключено» with the reason on hover; filter «Показати виключені» (default on).
- **Acceptance:** digest and Home totals with one excluded trade (strategy metrics exclude it, account P&L and limits include it); exclude -> re-sync -> still excluded; revert restores all metrics; missing reason -> 422. Owner check: exclude the XAUUSD test trade from 11.11 with reason «перевірка торгівлі на новому рахунку»; it leaves that week's digest strategy numbers while Home P&L does not change; revert, exclude again.

## M8-02 — Fill out an OPEN trade and complete it after closure (HIGH)

- **Owner wording:** record setup, emotions, reasoning and **before-entry charts while the position is still open**, not only after it closes.
- **Behaviour:** persist a partial description on the open position and allow later additions/editing of the **same** record when the trade closes; no loss/replacement on MT5 sync. Lifecycle OPEN -> CLOSED; no duplicate description, no fabricated exit data, safe linking to the source MT5 position/deals.
- **Open:** inspect schema and identity mappings (the current UI/DB is closed-trade-oriented) before choosing a solution.
- **PM authorization 2026-11-18 (tier L, branch `m8/open-trade-description`, together with M8-03):**
  - Open positions get a journal record as soon as sync sees them, keyed by account + MT5 position_id (the same id the closed trade will have). No duplicate record at close: the closed trade continues the same record.
  - «Описати» is available for open positions (from Home «Відкриті позиції» and the Journal). Text, voice and audio upload work as for closed trades. AI extraction on an open trade fills only pre-entry fields; exit fields (exit reason, after-trade notes) are never filled for an open trade.
  - Open trades are not in «Потрібен опис». On close, the record keeps everything already written; it enters «Потрібен опис» only if required fields are still missing, and the Describe screen highlights what is left (exit reason, after-trade fields, emotion after).
  - MT5 sync never overwrites the owner's text, fields or links on open or closed records; partial closes keep one record.
  - Statuses: open_draft -> (close) -> needs_description / draft / complete.
- **Acceptance (tests):** open -> describe -> close via sync -> same record, text kept, inbox behaviour; partial close; re-sync does not overwrite; AI on an open trade leaves exit fields empty (fixture, no live call). Owner check: open a small real or demo position, describe it with 2 «до входу» links while open, close it, then add an «після угоди» link and complete it.

## M8-03 — Better before/after chart link defaults

- **Owner wording:** usually **1–2 charts before entry** and **1–2 after exit**.
- **Behaviour:** when adding chart links, show **two «до входу» fields by default** first, then «після угоди» links later; flexible counts; clear labels; editable on open and closed trades. Empty placeholders are not mandatory links unless the owner approves.
- **Depends on:** M8-02 and the describe UI.
- **PM authorization 2026-11-18 (with M8-02):**
  - Each chart link has a type: before («до входу») or after («після угоди»).
  - Describe shows two empty «до входу» fields by default. «Після угоди» fields (one by default, «+ додати» for more) appear when the trade is closed. Any number allowed; empty fields are ignored on save.
  - Completion requires at least 1 «до входу» link (replaces the old "at least 1 link" rule). «Після угоди» is optional.
  - ~~Existing links: migrate as «без позначки»~~ — superseded by PM 2026-11-18: existing links keep the type the owner already chose (per-row select since M2); no «без позначки» group, no migration.
- **Acceptance (tests):** link types and the completion rule (>= 1 «до входу»); existing links keep their stored type.
- Status 2026-11-18: merged `5a05b6a` with M8-02, TECHNICAL ACCEPTED (PM), owner check pending (docs/reports/M8-02.md).

## M8-04 — Rule violation taxonomy updates

- **Owner wording, add:** «Вхід не за моделлю входу»; «Вхід від слабкої POI»; «Вхід не за торговою системою (не дотримуючись контексту H1/H4)».
- **Owner wording, consolidate:** «entry after daily stop-profit» and «entry after daily stop-loss» into a broader **daily risk violation**; also a **weekly risk violation**.
- **Open:** exact labels, how existing specific flags map, whether the old nuance stays for history/statistics. **Do not silently rewrite past records.** **Acceptance:** TBD by PM.

## M8-05 — Independent H1 and H4 context; combinations in statistics

- **Owner wording:** replace the single «H1 synchronized with H4» choice with two independent attributes **H1 context** and **H4 context**, each Flow / Reversal / Range / Other; Other requires a mandatory explanation. Examples: Flow H1/Flow H4, Reversal H1/Reversal H4, Flow H1/Reversal H4, Flow H4/Reversal H1; Range combinations follow naturally. Statistics analyse **H1×H4 combinations**.
- **Decision (migration):** old «Flow H1 synced with H4 = yes» -> H1 = Flow AND H4 = Flow; «no»/empty -> new fields empty, legacy value kept visible read-only.
- **Acceptance:** TBD by PM.

## M8-06 — Multi-select POI types and fractal options

- **Owner wording:** POI can be **FVG H1 and FVG H4** (and other categories) at once; keep existing POI choices, **add Fractal H1 and Fractal H4**, allow **multiple selections**; «Other» requires a description.
- **Open:** historical POI values stay accessible after migration; statistics/filter semantics to define. **Acceptance:** TBD by PM.

## M8-07 — Multi-select and conditional FVG type

- **Owner wording:** an FVG can both update a fractal and be a manipulation (multi-select). Show «FVG type» **only if POI includes FVG H1 and/or FVG H4**; no forced FVG type without an FVG POI.
- **Decision:** FVG type is per timeframe: separate multi-selects for FVG H1 and FVG H4, each shown only when that POI is selected.
- **Open:** whether hidden values are preserved or cleared when FVG is deselected (no silent data loss). **Acceptance:** TBD by PM.

## M8-08 — Entry model stays single-select; «Інше» explanation

- **Owner wording:** the one-entry-model selection is correct. If «Інше» is selected, **require a text description** of the actual model. Otherwise keep current choices and logic.
- **Acceptance:** TBD by PM.

## M8-09 — Exit reason (merged)

- **Owner wording:** exit price matches the initial SL -> «Stop Loss», matches TP -> «Take Profit»; otherwise the owner chooses manually. **PM proposal:** never overwrite an explicitly entered reason; allow manual override.
- **Decision:** primary source is the MT5 deal reason of the closing deal(s); price match vs initial SL/TP only as fallback with tick tolerance; partial closes handled explicitly.
- **Status:** merged `eb6e690`, report `docs/reports/M8-09.md`. Owner check pending on the next 3 closed trades. Trades #5 and #9 (EURUSD, 30.10 and 04.11) are «вручну» while MT5 says TP: confirmed by the owner as really manual.

## M8-10 — UI/UX research, redesign, branding/logo (HIGH discovery)

- **Owner wording:** the current UI is poor; wants a research-driven, professional redesign by a separate research/design agent (possibly Fable), using screenshots the owner supplies.
- **Behaviour (research only, no code/data/real API calls):** study TradeZella, TraderSync, Edgewonk, TradesViz, Tradervue, TradingView, Notion journals and at least one other; three visual directions (HEX palettes, typography, spacing, layout) with one recommendation; design system; three brand/logo concepts (icon, favicon, wordmark); page-by-page redesign (Dashboard, Journal, describe, Bias, Calculator, Digests, Settings, status bar) keeping workflows and Ukrainian copy; separate visual-only vs frontend UX vs backend/schema changes; top 15 improvements, P0/P1/P2 and S/M/L plan, Fable design brief and engineering handoff. Short brief: handoff §6.
- **Gate:** the owner picks a direction before any redesign implementation. **Acceptance:** TBD by PM.

## M8-11 — Footer overscroll (accepted)

- **Owner wording:** occasionally after switching/opening a page the whole page scrolls far below the content; the status bar appears mid-viewport with a large blank dark area below (seen on «Головна»).
- **Behaviour:** footer stays at the viewport bottom on every route; no blank area; no page-level horizontal scroll 1280–2560 px; long pages scroll only the content area; route change resets content scroll to top.
- **Acceptance:** Playwright regression (all main pages, short/long content, resize); owner check: 10 fast page switches, resize, zoom 90 %/110 %. **Owner PASS, PM accepted 2026-11-17.**

## M8-12..M8-16 — PM authorization 2026-11-18 (order M8-12 -> M8-16 -> M8-13 -> M8-14)

Each on its own branch, own report (max 15 lines), merge per CLAUDE.md; continue to the next after each merge. M8-04..M8-08 and M8-10 NOT authorized.

### M8-12 — Run without visible windows (M)
- No console window: all processes hidden. Tray icon: «Відкрити журнал», «Показати термінали» / «Сховати термінали», «Логи», «Зупинити».
- Autostart at Windows login ON (owner decision), hidden, tray only; toggle «Запускати з Windows» in Settings and the tray.
- Desktop shortcuts «Торговий журнал — Старт» / «— Стоп» with the app icon; idempotent installer script; README.
- MT5 portable terminals in the background: windows hidden after start and re-hidden if restored, no taskbar button; sync/margin/order_calc_profit work hidden. Never touch a terminal the owner opened.
- Console-only errors reach the UI status bar and logs.
- Owner check: reboot -> app starts, no PowerShell/MT5 windows, tray icon, sync works; «Стоп» stops cleanly; «Старт» starts again.

### M8-16 — MAE / MFE per trade (L)
- Owner wording: for every trade show how far price went against me and in my favour while open, in R; first my way then SL -> MFE in R; TP -> MFE at least the TP's RR.
- MFE_R / MAE_R = max favourable / adverse excursion from entry (open..close) / initial SL distance; store points and times. Long = bid, short = ask (DECISIONS). M1 bars; ticks (copy_ticks_range) for trades < 2 h or ambiguous minutes. No SL: points only. Open trades: running values «поточні». Worker after close, never blocking sync; backfill (dry run first). Migration + backup.
- UI: optional Journal columns «MAE, R» / «MFE, R»; trade details with points and times; digests: average MFE of winners/losers, count/share of losers that reached >= 1R first.
- Tests: long/short, TP, SL after favourable move, plain SL, partial close, gap through SL, missing SL, bid/ask. Owner check: 3 real trades within 0.1R of the chart.

### M8-13 — Choose the Claude model (M)
- Settings → ШІ: default model per call type (trade extraction, bias extraction, digest summary) from config/ai_models.yaml (id, label, approx price per call). One-off selector next to «Заповнити з тексту» and «Підсумок від ШІ» with approx cost. ai_usage.jsonl records the model used; a rejected model -> clear Ukrainian error. Fixture tests only.

### M8-14 — Charts on «Головна» (M)
- Equity curve, P&L by day (bars), rolling win rate and average R (20 strategy trades; excluded out). Range «Тиждень», «Місяць», «3 місяці», «Рік», «Усе», «Свої дати»; account selector (each / all); remembered per browser (localStorage in try/catch); defaults «Місяць», all; empty «Немає угод за цей період». Account currency and % of account size; Brussels dates; reuse digest chart components. Owner check: numbers match the digest for the same period.

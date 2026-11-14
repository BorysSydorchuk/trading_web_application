# M6 live check: dashboard and digests (M6-08 plan, draft 2026-11-14)

Status: **plan only**. Nothing below has been run yet. M6-08 starts after the PM review of
the first live AI summary (Borys, week 9–15 Nov). No AI calls in QA (`ANTHROPIC_API_KEY=""`).

Two kinds of evidence, never mixed:

- **[QA]**: isolated synthetic QA (own DB `trading_journal_qa_m6`, fixture MT5, hand-made
  trades, AI off). Proves the app follows the contract with known numbers.
- **[OWNER]**: Borys on the real app and real trades. Proves the real numbers and the screens.

ROADMAP M6 acceptance criteria and where each is proven:

| AC | Evidence | Status |
|---|---|---|
| Digest for a week with real trades matches hand-calculated win rate, total R and P&L | [OWNER] week 9–15 Nov and October, checked by the PM from screenshots 2026-11-14 | done (record in M6.md) |
| Deviations highlighted | [QA] history fixture (real history < 20 trading days, so the real app correctly shows «замало історії для норми») | to do |
| Review + next week's bias saved from one screen | [OWNER] item 6 below; [QA] item Q7 | to do |

## [QA] plan (qa-tester, root runs the gate)

Launcher `scripts/qa_live_check_m6.py`, same guards as `qa_live_check_m5.py` (only
`trading_journal_qa_m6` on localhost; refuses the dev DB, `_test` and older QA DBs; never
drops or resets; pre-migration `pg_dump` through `app.tools.migrate`; config copied unchanged
to `%TEMP%\tj-qa-m6`; refuses busy ports 8000/5173; never stops what it did not start).
Data are seeded through the real sync from a fixture MT5 file
`backend/tests/fixtures/mt5/digest_qa.json` (SYNTHETIC values, labelled as such).

Fixture design (two USD accounts, sizes 10 000 and 20 000):

- **History:** 6 full weeks before the test week (≥ 20 trading days), weekly win rate around
  60 % and total R around +1, so the norm exists for both scopes (combined and per account).
- **Test week Mon 2026-11-09:** hand-calculated in this file before the run:
  trades, wins/losses/breakeven (incl. one |R| < 0.1 trade = «в нуль» and one trade without
  R), net P&L in money and % of the active accounts' sizes, total R with n/N, win rate,
  avg win/loss R, expectancy, profit factor, max drawdown (money and %), best/worst trade.
  Win rate clearly below the norm (red), total R clearly above (green).
- **Edge cases:** Sunday 23:30 Brussels close (belongs to the week), archived account trade
  and an open trade (both excluded), one rule violation with known P&L, daily/weekly/monthly
  bias notes with marked results (accuracy and aligned/counter).

Checks (API through HTTP, UI in Chrome at 1280 px):

| # | Check | Expected |
|---|---|---|
| Q1 | `GET /api/digests?kind=weekly` before any create | virtual rows only for weeks with trades, «не переглянуто», newest first |
| Q2 | Open the test week | digest created on demand; every metric equals the hand calculation |
| Q3 | Highlights | win rate red, total R green, norm text «норма X ± Y»; a scope with < 20 trading days shows «замало історії для норми» |
| Q4 | Breakdowns, rules, bias | groups and «заповнено N/M» as hand-calculated; rule P&L cost; bias daily/weekly/monthly |
| Q5 | «Сума R» n/N link | opens Journal «Без R» with the trade without R only |
| Q6 | Charts | equity per account + combined starts at 0 and ends at net P&L; R buckets incl. «≤ −2.5»/«≥ 3»; heatmap cells |
| Q7 | Review + next-week bias on one screen | PATCH saves, list shows «переглянуто · <date>»; bias note created for next Monday; leaving with unsaved text asks first |
| Q8 | Suggestion | Fri 16:00 Brussels (clock injected): latest week only; reviewed → none |
| Q9 | Dashboard | today/week P&L vs limits, «СТОП на сьогодні» when the day passes −3 % of the account size, open positions, inbox counts |
| Q10 | Errors | AI button without key → «ШІ не налаштовано» inline + toast, no call; broken rules.yaml → readable config error |
| Q11 | Layout | no horizontal page scroll at 1280 px on Home, Дайджести list and digest page |

Gate: full `make check` on the final commit, code-reviewer (+ python-reviewer for the
launcher), then merge. No Whisper, no live AI, no real MT5.

## [OWNER] checklist (Borys, real app, about 10 minutes)

1. [OWNER] AI summary for week 9–15 Nov (done by Borys, 1 call): text and time sent to the PM.
   Read it for advice wording («варто», «слід», plans): none expected.
2. [OWNER] «Головна»: both FN accounts show today and week P&L in money and %
   (of the account size), limits, no stop banner unless a limit was passed.
3. [OWNER] «Дайджести»: weeks since 26 Oct and months October/November listed; the ones you
   did not open show «не переглянуто».
4. [OWNER] Week 9–15 Nov: numbers already checked by the PM; press «Оновити» once so the
   breakeven rule (|R| < 0.1 = «в нуль») applies, and note whether win rate changed.
5. [OWNER] If «Сума R» shows n/N with n < N, click it: the Journal opens with «Без R» and
   lists exactly the missing trades.
6. [OWNER] Same screen: fill the review, save; save next week's bias (16–22 Nov). The list
   then shows «переглянуто · 14.11.2026» (or the day you save).
7. [OWNER] Reminder on «Головна» for the week disappears after the review is saved.

Results go into `docs/reports/M6.md` (owner table).

## QA hand calculation (written before the run, M6-08)

Data: `backend/tests/fixtures/mt5/digest_qa.json` (SYNTHETIC, generator `build_digest_qa.py`).
All trades: commission/swap 0, EURUSD/GBPUSD contract 100 000, SL 20 pips, TP 50 pips
(planned RR 2.5), so `R = net / risk` exactly. Account A size 10 000 (0.45 lot, risk 90.00 =
0.90 %), B size 20 000 (0.90 lot, risk 180.00 = 0.90 %), C size 10 000 (archived after sync).
Server time ny_close (UTC+3 until 2026-11-01, then UTC+2), no ticks.

Deviations from the plan (technical):
- **Ports 8020 (API) / 5183 (UI)**, not 8000/5173: Borys's normal app keeps running. The
  launcher never starts `scripts/dev.py` except `--ensure-db` (dev.py run mode would stop the
  normal app); `frontend/vite.config.ts` reads `TJ_WEB_PORT` / `TJ_API_PORT` (defaults 5173/8000).
- **No worker.** One fixture source serves one login, and the QA needs three accounts. The
  seed step (`--seed`, `backend/tests/fixtures/mt5/digest_qa_seed.py`) runs the real
  `app.services.sync.sync_account` per account with a `FixtureMt5Source` at two pinned
  instants: pass 1 2026-10-17T12:00Z (initial_history_days 30 reaches back to Sep 17) and pass 2
  2026-11-15T23:00Z (from the last success − 3 days). C is synced in pass 2 only, then archived
  through `DELETE /api/accounts/{id}`. Bias notes/results and draft journals go through the API.
- **Pinned clock:** the QA API is the normal `app.main:app` with `app.clock.utc_now` (and
  `sync_status.utc_now`) overridden to read `%TEMP%\tj-qa-m6\clock.txt` on every request;
  `--set-now` rewrites it. Default 2026-11-13T15:00:00Z = Fri 16:00 Brussels.

History (6 weeks; R per trade in slot order A Mon 09:00 EURUSD, B Tue 14:00 GBPUSD, A Wed 09:30
EURUSD, B Thu 09:00 EURUSD, A Fri 14:00 GBPUSD; all buys with SL):

| week | R | trades | wins | win rate | total R | net |
|---|---|---|---|---|---|---|
| 09-28 | +2, −1, +1, −1, −1 | 5 | 2 | 40 % | 0 | −180.00 |
| 10-05 | +1.5, −1, +1, +0.5, −1 | 5 | 3 | 60 % | +1 | 45.00 |
| 10-12 | +2, −1, −1, +1, +1 | 5 | 3 | 60 % | +2 | 180.00 |
| 10-19 | −1, +1.5, +1, −1, +0.5 | 5 | 3 | 60 % | +1 | 135.00 |
| 10-26 | +1, +1, −1, +1, −1 | 5 | 3 | 60 % | +1 | 270.00 |
| 11-02 | +1, +0.5, +1, −1, +0.5 | 5 | 4 | 80 % | +2 | 135.00 |

First trade Mon 09-28 → 30 weekdays before 11-09 (≥ 20: norm available for combined, A, B).
Week 10-12: 10 weekdays → `norm_available` false («замало історії для норми»).

Test week Mon 2026-11-09 (Brussels times; close order T1 T6 T7 T2 T3 T8 T4 T5 T9):

| # | acc | symbol dir | open → close | session/hour | R | net | outcome | notes |
|---|---|---|---|---|---|---|---|---|
| T1 | A | EURUSD buy | Mon 09:00 → 10:00 | london 9 | 5.0000 | 450.00 | win | daily bias aligned; entry_model ifvg_m5 |
| T6 | B | GBPUSD buy | Mon 14:00 → 15:00 | ny 14 | −1.0000 | −180.00 | loss | |
| T7 | B | EURUSD sell | Tue 09:00 → 10:00 | london 9 | – | −54.00 | loss | no SL → no R (needs_sl) |
| T2 | A | GBPUSD sell | Tue 14:00 → 15:00 | ny 14 | −1.0000 | −90.00 | loss | |
| T3 | A | EURUSD buy | Wed 09:30 → 10:30 | london 9 | 0.0500 | 4.50 | breakeven (abs R < 0.1) | |
| T8 | B | EURUSD buy | Thu 09:00 → 10:00 | london 9 | −1.0000 | −180.00 | loss | entry_model qm_m5 |
| T4 | A | EURUSD buy | Fri 13:30 → 14:00 | ny 13 | −3.5000 | −315.00 | loss | A day −3.15 % → STOP; daily bias counter; ifvg_m5 |
| T5 | A | GBPUSD buy | Fri 14:30 → 15:00 | ny 14 | 0.5000 | 45.00 | win | daily_stop_loss_pct violation (entry after −3 %) |
| T9 | B | EURUSD buy | Fri 15:00 → Sun 23:30 (22:30Z) | ny 15 | 4.0000 | 720.00 | win | Sunday close belongs to the week; daily bias counter |
| T10 | B | GBPUSD sell | Thu 14:00 → open | ny 14 | – | – | open | excluded; risk 180.00 |
| C1 | C | EURUSD buy | Wed 09:00 → 10:00 | london 9 | 2.0000 | 180.00 | win | archived account: excluded |

Bias (API): monthly 11-01 EURUSD bullish (correct); weekly 11-09 EURUSD bullish (correct),
GBPUSD bearish (wrong); pre_london 11-09 EURUSD bullish (correct); pre_london 11-12 XAUUSD
neutral (unmarked); pre_ny 11-13 EURUSD bearish (wrong).

### Q2 expected (snapshot strings: money 2 dp, else 4 dp, ROUND_HALF_UP)

| metric | combined | A | B |
|---|---|---|---|
| trades / wins / losses / breakeven | 9 / 3 / 5 / 1 | 5 / 2 / 2 / 1 | 4 / 1 / 3 / 0 |
| violations | 1 | 1 | 0 |
| net_pnl | 400.50 | 94.50 | 306.00 |
| net_pnl_pct (base 30 000 / 10 000 / 20 000) | 1.3350 | 0.9450 | 1.5300 |
| total_r (n/N) | 3.0500 (8/9) | 1.0500 (5/5) | 2.0000 (3/4) |
| win_rate | 33.3333 | 40.0000 | 25.0000 |
| avg_win_r | 3.1667 | 2.7500 | 4.0000 |
| avg_loss_r | −1.6250 | −2.2500 | −1.0000 |
| expectancy_r | 0.3813 | 0.2100 | 0.6667 |
| profit_factor (money) | 1.4890 (1219.50/819) | 1.2333 (499.50/405) | 1.7391 (720/414) |
| max_drawdown | 814.50 (450 → −364.50) | 400.50 (450 → 49.50) | 414.00 (0 → −414) |
| max_drawdown_pct | 2.7150 | 4.0050 | 2.0700 |
| best / worst | T9 720.00 / T4 −315.00 | T1 450.00 / T4 −315.00 | T9 720.00 / T6 −180.00 (tie with T8, earlier close) |

### Q3 expected norms (mean ± population SD of the 6 history weeks, sigma 1.0)

| scope | win_rate | total_r | other metrics |
|---|---|---|---|
| combined | 33.3333 vs 60.0000 ± 11.5470 → **worse (red)** | 3.0500 vs 1.1667 ± 0.6872 → **better (green)** | better: net_pnl (97.50 ± 140.91), net_pnl_pct (0.3250 ± 0.4697), avg_win_r (1.0972 ± 0.2473), expectancy_r (0.2333 ± 0.1374); worse: max_drawdown (210.00 ± 84.85), max_drawdown_pct (0.7000 ± 0.2828); none: trades (5 ± 0), violations (0 ± 0), avg_loss_r (−1 ± 0), profit_factor (1.5306 ± 0.5782) |
| A | 40.0000 vs 66.6667 ± 19.2450 → worse | 1.0500 vs 1.2500 ± 1.1815 → none | better: avg_win_r (1.1389 ± 0.2992); worse: max_drawdown (90.00 ± 51.96), max_drawdown_pct (0.9000 ± 0.5196); none: net_pnl (112.50 ± 106.33), net_pnl_pct, expectancy_r (0.4167 ± 0.3938), profit_factor (2.1000 ± 0.9695), trades, violations, avg_loss_r |
| B | 25.0000 vs 50.0000 ± 28.8675 → none | 2.0000 vs −0.0833 ± 1.2047 → better | better: net_pnl (−15.00 ± 216.85), net_pnl_pct (−0.0750 ± 1.0843), avg_win_r (0.9000 ± 0.3742, weeks without a win dropped), expectancy_r (−0.0417 ± 0.6024), profit_factor (0.7000 ± 0.5099, weeks without a loss dropped); worse: max_drawdown (180.00 ± 103.92), max_drawdown_pct (0.9000 ± 0.5196); none: trades, violations, avg_loss_r |

### Q4 expected (combined, test week; group = trades / net / total R / win rate)

- symbol: EURUSD 6 / 625.50 / 4.5500 / 33.3333; GBPUSD 3 / −225.00 / −1.5000 / 33.3333; 9/9.
- session: london 4 / 220.50 / 4.0500 / 25.0000; ny 5 / 180.00 / −1.0000 / 40.0000; 9/9.
- hour: 9 → 4 / 220.50 / 4.0500 / 25; 13 → 1 / −315.00 / −3.5000 / 0; 14 → 3 / −225.00 / −1.5000 / 33.3333; 15 → 1 / 720.00 / 4.0000 / 100.
- weekday: 0 → 2 / 270.00 / 4.0000 / 50; 1 → 2 / −144.00 / −1.0000 / 0; 2 → 1 / 4.50 / 0.0500 / 0; 3 → 1 / −180.00 / −1.0000 / 0; 4 → 3 / 450.00 / 1.0000 / 66.6667.
- bias_alignment (daily): aligned 1 / 450.00 / 5.0000 / 100; counter 2 / 405.00 / 0.5000 / 50; no_bias 6 / −454.50 / −2.4500 / 16.6667; 9/9.
- entry_model: ifvg_m5 2 / 135.00 / 1.5000 / 50; qm_m5 1 / −180.00 / −1.0000 / 0; (empty) 6 / 445.50 / 2.5500 / 33.3333; «заповнено 3/9». Other journal fields 0/9.
- rules: daily_stop_loss_pct 1 violation, 1 trade, P&L 45.00; violated trades 1, P&L 45.00.
- bias: daily accuracy 50.0000 (marked 2 / total 3), aligned 1 / 450.00 / 5.0000, counter 2 / 405.00 / 0.5000; weekly 50.0000 (2/2), aligned 6 / 589.50 / 3.5500, counter 3 / −189.00 / −0.5000; monthly 100.0000 (1/1), aligned 5 / 679.50 / 4.5500, counter 1 / −54.00 / 0.0000.

### Q1, Q5–Q10 expected

- Q1 (clock Fri 11-13 16:00, no digest yet): 7 weekly virtual rows (id null, «не переглянуто»,
  total_r/win_rate null), newest first: 11-09 9 / 400.50; 11-02 5 / 135.00; 10-26 5 / 270.00;
  10-19 5 / 135.00; 10-12 5 / 180.00; 10-05 5 / 45.00; 09-28 5 / −180.00 (C1 not counted).
- Q5: `GET /api/trades?from=2026-11-09&to=2026-11-15&missing_r=true&account_id=A&account_id=B`
  (the link built by `missingRPath`) → total 1, T7 only (the open T10 is not "closed without R").
- Q6: equity combined 0.00 at 2026-11-08T23:00:00Z, then 450.00, 270.00, 216.00, 126.00,
  130.50, −49.50, −364.50, −319.50, **400.50**; A 0 → 450, 360, 364.50, 49.50, **94.50**;
  B 0 → −180, −234, −414, **306.00**. R buckets −3.0 … 3.0 (13): [−3, −2.5) 1 («≤ −2.5»),
  [−1, −0.5) 3, [0, 0.5) 1, [0.5, 1) 1, [3, 3.5) 2 («≥ 3»), others 0. Heatmap 9 cells, 1 trade
  each: (0,9) 450, (0,14) −180, (1,9) −54, (1,14) −90, (2,9) 4.50, (3,9) −180, (4,13) −315,
  (4,14) 45, (4,15) 720.
- Q7: PATCH review → `reviewed` true, `reviewed_at` 2026-11-13T15:00:00Z (pinned); list row
  reviewed; POST weekly bias 2026-11-16 → 201, digest `next_bias_note_id` = its id.
- Q8: 14:59:59Z (15:59:59 Brussels) → weekly 2026-11-02, monthly 2026-10-01; 15:00:00Z →
  weekly 2026-11-09; after the Q7 review → weekly null, monthly still 2026-10-01.
- Q9 (15:00Z): A today −270.00 (−2.7000 %), low −315.00 (−3.1500 %) → `stop_loss`
  («СТОП на сьогодні»), week 94.50 (0.9450 %), high 450.00 (4.5000 %), ok; B today 0, week
  306.00 (1.5300 %; includes the Sunday T9 that is "future" for the pinned clock), low −414.00
  (−2.0700 %), ok; stop.today true, stop.week false; open positions 1 (T10, risk 180.00,
  0.9000 %); inbox needs_sl 1, draft 3, needs_description 35 (39 closed active − T7 − 3 drafts).
- Q10: `POST /api/digests/{id}/ai-summary` → 503 `ai_not_configured`, no AI call; broken
  QA-copy `rules.yaml` → 500 `config_error` on dashboard and digest create; restored → 200.

## [QA] results (run 2026-11-14, qa-tester)

Commands: `python scripts/qa_live_check_m6.py --seed` (created + migrated `trading_journal_qa_m6`,
backup `backups/pre-migration-cdb0477c3b70-20261114T165148Z.dump`; sync pass 1 A 9 / B 6
trades, pass 2 A 14 / B 11 (+1 open) / C 1, all `ok`), then `python scripts/qa_live_check_m6.py`
(API 127.0.0.1:8020 with the pinned clock, UI 127.0.0.1:5183 proxying to 8020; API seed:
5 bias notes + results, 3 draft journals, C archived). Checks over HTTP by a throw-away
driver (56 assertions, expected values = the hand calculation above, copied before the run).
The normal app on 8000/5173 answered 200 before and after; nothing of it was stopped.
No AI call (key empty), no Whisper, no MT5 terminal.

| # | Expected | Actual | Result |
|---|---|---|---|
| Q1 | 7 weekly virtual rows, newest first, all «не переглянуто», counts/net as in the table | identical (11-09 9 / 400.50 … 09-28 5 / −180.00, id/total_r/win_rate null) | PASS |
| Q2 | combined / A / B metrics, n/N, best/worst as in the Q2 table | all 15 metrics × 3 scopes identical, n 8 / 5 / 3, best/worst identical (B worst = T6, earlier tie) | PASS |
| Q3 (API) | win_rate worse, total_r better (combined); every norm mean/SD/deviation as in the Q3 table; week 10-12 `norm_available` false | identical for combined, A, B; week 10-12 false for combined and both accounts | PASS |
| Q4 | breakdown groups, coverage (entry_model 3/9, other journal fields 0/9), rules (daily_stop_loss_pct 1 / 45.00), bias daily/weekly/monthly | identical | PASS |
| Q5 (API) | `missing_r` list for 11-09..11-15 and accounts A, B = T7 only | total 1, position 8100140 (T7) | PASS |
| Q6 (API) | equity combined/A/B from 0 at 2026-11-08T23:00Z to 400.50 / 94.50 / 306.00; 13 R buckets incl. [−3, −2.5) 1 and [3, 3.5) 2; 9 heatmap cells | identical | PASS |
| Q7 (API) | PATCH → reviewed, `reviewed_at` 2026-11-13T15:00:00Z; list row reviewed; weekly bias 11-16 201 and `next_bias_note_id`; snapshot unchanged | identical (note id 6) | PASS |
| Q8 | 15:59:59 Brussels → weekly 11-02, monthly 10-01; 16:00 → weekly 11-09; after review → weekly null, monthly 10-01 | identical | PASS |
| Q9 (API) | A today −270.00 / low −315.00 (−3.15 %) → `stop_loss`, week ok; B ok; stop.today true, week false; 1 open position (GBPUSD sell, risk 180.00); inbox 1 / 35 / 3 | identical | PASS |
| Q10 | AI summary → 503 `ai_not_configured`, ai_summary stays null; broken QA-copy rules.yaml → 500 `config_error` (dashboard and digest create, message names the file and line) and logged in `logs/api.log`; restored → 200, stored digest unchanged | identical | PASS |
| Q11, UI parts of Q3/Q5/Q7 | layout at 1280 px, colours/texts, Journal «Без R» page, unsaved-text prompt | not run by qa-tester | for the root's Chrome check |

How the clock is pinned (Q8): the launcher starts the normal `app.main:app` with
`dependency_overrides[app.clock.utc_now]` (and `sync_status.utc_now`) returning the instant in
`%TEMP%\tj-qa-m6\clock.txt`, read on every request; `--set-now 2026-11-13T14:59:59Z` rewrote it
between requests without a restart. Every M6 endpoint takes "now" from that dependency.

Notes:
- With the clock on Fri 11-13 the dashboard week of B includes T9 (closes Sun 11-15, a
  "future" close for the pinned clock): the dashboard does not filter closes after now. Not
  reachable with real data (a trade cannot close in the future); recorded, no change.
- The «no AI usage log» check only looked at `<base>/logs`; the stronger evidence is the
  endpoint order (503 before any client call) and the empty key.
- The QA DB now holds the reviewed 11-09 digest and a 10-12 digest; the 11-02 week is still
  unreviewed (usable for the unsaved-text prompt in the UI check).

## [ROOT] Chrome check on the QA app (2026-11-14, 1280 px viewport, clock Fri 2026-11-13 16:00 Brussels)

| # | Check | Result |
|---|---|---|
| Q11 | No horizontal page scroll: «Головна», «Дайджести» list, digest page week 9–15 Nov | PASS (scrollWidth − clientWidth = 0 on all three) |
| Q3 (UI) | Combined block: win rate red «33.33% (гірше норми) норма 60.00 ± 11.55», total R green «+3.05R (краще норми) норма 1.17 ± 0.69» | PASS |
| Q5 (UI) | «за 8/9 угод» is a link; it opens Journal with «Без R» checked, period 9–15 Nov, accounts 1 and 2, exactly one row (QA M6 B EURUSD, −54.00) | PASS |
| Q7 (UI) | Week 2–8 Nov: typed review text, clicked «Головна» → dialog «Зміни не збережено», stayed on the page; «Піти без збереження» leaves (nothing saved) | PASS |
| Q8/Q9 (UI) | «Головна»: «СТОП на сьогодні» banner, account A −2.70 % badge «СТОП: ліміт збитку», reminder «Час переглянути місяць: жовтень 2026» (week 9–15 already reviewed → no weekly reminder); «Дайджести» list: week 9–15 «переглянуто · 13.11.2026», older weeks «не переглянуто» | PASS |

Cosmetic (not blocking): at 1280 px the Home limit table wraps «−270.00 USD» onto two lines inside the account card (no page scroll). BACKLOG.
QA app stopped with `python scripts/qa_live_check_m6.py --stop`; Borys's app on 8000/5173 untouched.

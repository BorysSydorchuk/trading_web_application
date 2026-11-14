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

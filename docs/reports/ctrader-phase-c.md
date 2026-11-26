# cTrader integration, phase c: symbol specs, FX rates, risk, calculator, MAE/MFE, limits

Firm (PM 2026-11-26): the cTrader account is a **KeyFunding** account, not FundedNext; its firm rules are in `config/firms.yaml` (docs/reports/keyfunding-firm-rules.md).

Tier L, no migration. Owner request 2026-11-24 (task c). Branch `ctrader/phase-c` from main 6f79e64.
Contract: `docs/api.md`, section "cTrader integration, phase c" (c1–c6).

## What was built

- **Read-only allowlist.** It adds only 2112 (assets), 2137 (trendbars) and 2145 (tick data). The guard test pins
  the full set and refuses the responses 2113, 2138 and 2146 as outgoing messages.
- **c1, symbol specs** (`ctrader/specs.py`, `ctrader/market.py`, `services/ctrader_specs.py`):
  - What gets specs: the config symbols (resolved with aliases and firm overrides, as for MT5), the symbols traded
    in this read, and the conversion pairs.
  - Where they go: the existing `symbol_specs` columns.
  - Formulas, all exact Decimal: contract size = lotSize / 100, tick = 10^-digits, lots = volume / lotSize.
  - A value that does not fit NUMERIC(20,8) is skipped with a WARNING, never rounded.
  - Refresh: the first cycle, then at most hourly, or sooner when a traded symbol has no stored spec.
- **c2, FX rates:**
  - Pair choice is the same rule as MT5: a direct pair uses the last ASK tick, an inverse pair uses 1 / last BID.
  - Ticks come from the last 60 min, else from the last 3 days.
  - The rate is stored through the shared `upsert_rates`.
  - The review added three checks. Each one gives no quote and keeps the stored rate:
    - A partial (`hasMore`) tick answer is asked again after its latest tick, at most 8 times, so a stale tick is
      never used.
    - BID and ASK ticks more than 15 min apart.
    - BID above ASK.
- **c3, risk:** open and closed cTrader trades get their risk from the initial SL and the spec. Cross-currency risk
  uses lot size × tick × rate (the MT5 rule). With no rate row the trade has no risk, but the sync stays ok.
- **c4, calculator:**
  - Lots work for cTrader accounts with the same formula as MT5.
  - Live margin is MT5 only. For cTrader the UI shows the estimate plus «Для рахунку cTrader маржу тут не рахуємо:
    дивіться її в cTrader.»
- **c5, MAE/MFE** (`ctrader/excursions.py`):
  - Definitions, targets and storage are the same as M8-16.
  - The series is made of ticks in the entry and exit minutes plus BID M1 trendbars between them.
  - A short also gets the median spread of its entry and exit ticks.
  - `hasMore` is handled by halving the window, at most 16 requests.
  - Budget: 8 s per account. Targets are tried least-recently-tried first.
- **c6, limits:** they needed no new code. Tests show that one account gives the same limits and daily-stop state on
  both platforms, and that the closest-to-stop pick works across platforms.
- **Time budget:** the 45 s read budget now keeps a reserve of 5 s for each account still to read, so one account's
  optional steps cannot use up a later account's balance time.

## Tests

- Fixtures only: recorded and sanitized, in `backend/tests/fixtures/ctrader/`, with a fake server. There are no live
  calls.
- New tests: `test_ctrader_phase_c_specs.py`, `test_ctrader_phase_c_job.py`, `test_ctrader_calculator.py`,
  `test_ctrader_limits.py`, `test_ctrader_excursions.py`, `test_ctrader_excursions_job.py`,
  `test_ctrader_excursions_reader.py`, `test_ctrader_ticks_paging.py`, and `CalculatorMargin.test.tsx` (cTrader case).
- Targeted runs: 207 phase c backend tests. Of these, 201 ran before the review fixes, and 6 tick-paging tests were
  added with the fixes.
- After the fixes, 933 cTrader, calculator, excursion and fx backend tests ran: 932 passed. The one failure was a
  flaky test in `test_ctrader_calculator.py`: its two accounts got rates from different `now()` calls. It now uses
  one fixed rate time, and the file then passed 6 runs out of 6.
- Full gate (`make check`, 2+2 workers) on e7b7ecc: free RAM 3.5 GB, 4704 backend passed / 1 skipped, 797 frontend,
  lint/typecheck PASS (`logs/gate-phase-c-20261124-2.log`). The first run on 1c3005e stopped at mypy on a test file
  (fixed in e7b7ecc). Merge `2e02294`; its tree equals the gated tree.

## Reviews

- **python-reviewer: APPROVE.** It raised 5 MEDIUM items, all fixed:
  - the per-account time reserve;
  - `hasMore` tick paging;
  - BID and ASK ticks of different ages;
  - catch-all errors in the market step;
  - tracebacks kept in the logs.
- **code-reviewer: APPROVE.** Its MEDIUM item about full tracebacks is fixed. Its MEDIUM item about repeated spec
  refreshes for a symbol that is always skipped went to the backlog. That only happens with a malformed broker spec.
- The LOW items went to `docs/BACKLOG.md`: cursor paging for MAE/MFE once the tick order is confirmed live, and the
  docs/api.md c1 wording.
- No database-reviewer, because there is no migration.

## Known issues and assumptions (to confirm in the first live check)

- These are assumptions from the Open API docs, not yet seen live:
  - Tick data and trendbar encoding: the first entry is absolute and later entries are deltas.
  - Prices are in 1/100000.
  - The order of a `hasMore` answer is unknown. The code works with either order.
- The live check waits for the Open API credentials in `.env`. Phases a, b and c are technical only so far.

## Commit range

6f79e64..2e02294 (merge), branch `ctrader/phase-c`.

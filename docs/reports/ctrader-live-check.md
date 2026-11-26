# cTrader phases a-c: first live read-only check (2026-11-26)

Account: KeyFunding «Two Step Lite Assessment (Phase 1) $100k» on the GooeyTrade cTrader server, demo (is_live false), app id 4,
size 100 000 USD. Connected by Borys at about 19:14 Brussels after the restart on main c5e0fd1. OAuth scope: accounts only.

## What the live data confirmed (no code change needed)
- **a. OAuth, accounts, balance/equity:** the connect, the callback and the account list work. The worker cycle
  reads balance 98 022.17 and equity 98 555.92 (two open positions). Errors: none in `logs/worker.log` / `logs/api.log`.
- **b. Deals into trades:** 13 deals became 7 trades: 5 closed and 2 open. Balance 98 022.17 = 100 000 + the net of the 5 closed
  trades (−1 176.76 − 1 008.75 − 1 093.12 + 2 401.20 − 1 100.40), exact to the cent.
  - The P&L matches price × volume × contract on every trade (for example XAUUSD 0.9 × 26.75 × 100 = 2 407.50).
  - Commission is 7 USD per lot on FX/XAU and 0 on GER40.
  - Times are UTC and the sessions are right (Brussels london/ny).
- **c. Specs, FX, risk, calculator:**
  - Specs: EURUSD/GBPUSD/USDCHF contract 100 000, XAUUSD 100, GER40 1 (tick 0.1 = 0.1 EUR).
  - Symbol names equal the canonical names: no aliases needed in `config/symbols.yaml`.
  - The FX rate comes from live ticks: EURUSD 1.09701, so the tick encoding and price scale are right.
  - The open-position risk is computed: GER40 0.9962 %, GBPUSD 0.8540 %.
  - The calculator gives GER40 entry 25 234.0 / SL 25 109.6 / 1 % = **7.3 lots**, the same as Borys's own cTrader position.
    EURUSD 10 pips / 1 % = 10.0 lots (1 000 USD).
- **Firm rules:** «Key Funding» matches the KeyFunding entry. The firm day floor is 94 022.17 = start balance − 4 % of 100 000.

## Still open
- **The 5 closed trades opened before the connection have no initial SL** (`needs_sl`), so they have no R, risk % or MAE/MFE.
  - Cause: the history read (deals) carries no SL. The SL is only seen on a position the app sees open. This is the known
    phase-b limit.
  - Workaround: Borys enters the initial SL in «Потрібен опис».
  - Possible fix: read the order history (an extra read-only payload type). Needs PM authorization (tier L).
- MAE/MFE was not seen live yet: it needs a closed trade with an SL. Check after the next trade that closes.
- Owner comparisons still to be done by Borys: «Баланс»/«Еквіті» vs cTrader, one closed trade's «Net», the calculator
  lot, and the status bar.

## Fixtures
No live format differed from the recorded fixtures, so no new fixture was needed.

# cTrader integration, phase b: deals become trades, open positions, reconcile

Firm (PM 2026-11-26): the cTrader account is a **KeyFunding** account, not FundedNext; its firm rules are in `config/firms.yaml` (docs/reports/keyfunding-firm-rules.md).

Tier L, no migration. Owner request 2026-11-23 (STEP 2). Branch `ctrader/phase-b` from main 6212dc3.

## What was built

- **One writer for both platforms.** The trade-writing half of `services/sync.py` moved without change into
  `services/trade_writer.py` (`write_trades`). MT5 calls it after the account values, specs and FX are written. The MT5 tests
  stayed green.
- **cTrader reading** (`ctrader/history.py`, read-only):
  - Open positions come from reconcile (2124).
  - Deal history (2133) is read in windows of at most one week. When `hasMore` is set, the window is halved.
  - Symbol names come from 2114. Digits and lot size come from 2116.
  - The allowlist grew only by 2114, 2116 and 2133. A test pins the allowlist and checks that every request type is on it.
- **Conversion** (`ctrader/convert.py`):
  - Deals are grouped by positionId. Partial closes use `closedVolume`.
  - Money comes from `closePositionDetail` (gross profit, swap, commission, conversion fee), scaled by `moneyDigits`.
  - Lots = volume / `lotSize`, as an exact Decimal. Timestamps are UTC ms. Aliases come from `config/symbols.yaml` (GER40/DE40).
- **Reconcile:**
  - A new position that cTrader does not report and the history does not close is not written. The run is ok with
    `positions_skipped` and a visible message, and the position is retried next cycle.
  - A DB-open trade that cTrader no longer reports stays `close_unconfirmed`, as for MT5.
  - The history window moves only after an ok run that read deals and skipped nothing.
  - A funded account with no deals closes nothing.
  - New error `history_incomplete`: an open position has no entry deal. In that case nothing is written.
- **Stops:**
  - The initial SL is the first SL seen on the open position.
  - When a position is closed, its stored last SL and TP are kept, so a trailed SL and a TP survive the close.
- **Worker:** balance, equity and trades are read in one connection and logged in one `sync_log` row. Trades are written
  in a savepoint, so a failed history read keeps the balance. Home shows cTrader positions with their P&L. There is no price, because
  cTrader sends no quote.
- **UI:**
  - The sync details show «Відкриті позиції» for cTrader.
  - Home no longer shows a false «дані застаріли» on a fresh cTrader position.
  - The close-unconfirmed hint does not name a platform.
  - The Ukrainian text for `history_incomplete` was added.

## Tests

- Recorded, sanitized fixtures in `backend/tests/fixtures/ctrader/`, with a fake server. There are no live calls.
- The tests cover:
  - a simple closed trade (net 19.30, R 1.93, in «Потрібен опис»), and a partial close;
  - commission + swap + fee, a position spanning two windows, and `hasMore` paging;
  - an open position on Home, a ghost position (not written), and a position gone without a close;
  - an empty read and a skipped run, neither moving the window;
  - a trailed SL and a TP kept through the close, and an equity failure with trades still written;
  - MT5 left untouched, and the guard allowlist pinned.
- Full gate: see the merge commit message.

## Reviews

- python-reviewer CHANGES REQUESTED: 1 HIGH (ghost open trade), 3 MEDIUM, 3 LOW. All were fixed, then APPROVE.
- code-reviewer CHANGES REQUESTED: 2 HIGH (TP/SL wiped on close, false stale note on Home), 2 MEDIUM, 4 LOW. All were fixed, then APPROVE.

## To confirm on the first live run

- **Field names.** These were assumed: `dealStatus`, `filledVolume`, `executionPrice`, `executionTimestamp`, `tradeSide`,
  `closePositionDetail{grossProfit, swap, commission, pnlConversionFee, closedVolume, moneyDigits}`,
  2125 `position[].tradeData{...}`, `stopLoss`, `takeProfit`, 2114/2116 symbol fields.
- **Net P&L.** Compare the net of one closed trade with cTrader History «Net». This checks the assumption that the entry
  commission is inside `closePositionDetail`.
- **Ranges.** Check whether DealList ranges are inclusive.

## Known limits (phase c or later)

- There is no exit reason, symbol specs, calculator, or MAE/MFE for cTrader yet.
- `balance_at_open` ignores cTrader deposits and withdrawals.
- A trade opened and closed between two syncs gets `needs_sl`, because the order history is not read.
- Each cycle re-reads history from the oldest DB-open trade. That is up to about 53 requests, about 11 s per account, inside the 45 s budget.
- Netting-account reversals are not verified.

## Memory diagnosis before the gate (2026-11-24)

The first gate attempt never started: free RAM stayed about 2.3 GB, below the 3 GB rule.

Snapshot 14:17 Brussels, app running (before stop.bat): free RAM 3.43 GB of 15.68 GB.
Top processes by working set (all instances summed):

| Process | Count | MB |
|---|---|---|
| chrome | 19 | 2395 |
| msedgewebview2 | 25 | 2300 |
| claude | 10 | 1916 |
| svchost | 82 | 1504 |
| explorer | 1 | 491 |
| NVIDIA Overlay | 5 | 415 |
| python (API + worker + tray) | 6 | 336 |
| rsAppUI | 4 | 333 |
| rsEngineSvc | 1 | 293 |
| terminal64 (MT5) | 2 | 266 |

The worker was 147 MB: the Whisper model was not loaded (no voice note since the start).
The app itself is not the memory problem; browsers/webviews and Claude take about 6.6 GB.

Second snapshot 14:41 Brussels, after stop.bat and closing extra Chrome tabs: free RAM 4.64 GB (+1.2 GB).
No python process left. Top: TradingView 2498 MB (12), claude 1865 (10), chrome 1475 (15),
svchost 1261 (76), msedgewebview2 1008 (18), Memory Compression 524, explorer 374, NVIDIA Overlay 296,
rsEngineSvc 292, rsAppUI 257. The RAM check (>= 3 GB) passes with TradingView open.

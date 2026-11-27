# cTrader initial SL from the order history (tier L, PM 2026-11-27)

Branch `ctrader/order-sl`. No migration. MT5 strictly unchanged.

## What was built
- Guard allowlist + one read-only type: 2183 `OrderListByPositionIdReq` (verified in the official
  `openapi-proto-messages` enum: 2183/2184). Still no trading message can be sent (guard tests).
- `app/ctrader/orders.py`: order parser, paged read (week windows, `hasMore` halving), and the rule:
  opening order `stopLoss`, else `relativeStopLoss` from its `executionPrice`, else the earliest
  protective (`STOP_LOSS_TAKE_PROFIT`) order. Only a stop on the loss side of the entry counts.
- Sync: positions closed in a read that the app never saw open (closed before the connection,
  while the app was off, or between two syncs) get their orders read (at most 10 per sync).
  The SL goes into the trade as source `order`; an owner SL (`user`) is never overwritten.
- Tool: `uv run python -m app.tools.backfill_ctrader_sl [--apply] [--account ID]`, dry run by
  default, log `logs/backfill_ctrader_sl.log`.

## MT5 (same principle)
Already in place since M1: each position in the sync window reads the opening deal's sl, then
the opening order (`history_orders_get(ticket=...)`), also when it opened and closed while the
app was off. Dev DB: 0 closed MT5 trades without an SL. Nothing changed.

## Dry run on the real account (2026-11-27 ~14:35 Brussels, Borys's OK, read-only)
| Trade | Symbol | Entry | SL found | From |
|---|---|---|---|---|
| 34 | USDCHF buy | 0.84256 | 0.84157 | opening order sl (protective later 0.84148) |
| 35 | GER40 buy | 25266.6 | 25201.0 | opening order sl = protective |
| 36 | GER40 buy | 25271.6 | 25172.5 | opening order sl = protective |
| 37 | XAUUSD sell | 3529.19 | 3540.40 | opening order sl = protective |
| 38 | EURUSD sell | 1.09467 | 1.09541 | opening relativeStopLoss 74 = protective 1.09541 |
| 41 | GER40 buy | 25391.7 | 25327.5 | opening order sl (8-second trade between two syncs) |

6 of 6 found, 0 errors, nothing written. Trade 41 is a new case found today: an 8-second trade
closed between two syncs, now covered by the sync step too.

Live format notes: market orders carry the absolute `stopLoss` (5 of 6) or only
`relativeStopLoss` (1 of 6); protective orders come with `closingOrder: true` and the price in
`stopPrice`. Trade 34: the protective stop (0.84148) differs from the opening SL (0.84157), so the
SL was moved after the open; the rule takes the opening one (the SL attached at open).

## Apply
See the STATUS line / the final section below once applied.

## Known limits
- The order history keeps an order's last state: with no SL on the opening order, a protective
  order moved later gives the moved price (DECISIONS 2026-11-27).
- More than 10 never-seen-open closed positions in one sync: the rest stay `needs_sl` (WARNING),
  the tool covers them.

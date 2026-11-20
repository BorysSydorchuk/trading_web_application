# Open trade shown after its close (owner bug 2026-11-20, tier M)

Trade 30: GBPUSD Sell 0.57, «FN Stellar Funded 2», position 211535896.

## Timeline (UTC)

| Time | Event | Evidence |
| --- | --- | --- |
| 14:05:02 | Position opened | DB `trades.open_time`, MT5 entry deal 196946946 |
| 16:19–20:35 | App on Docker after `switch-back` (owner console); syncs saw the position **open** | sync_log rows copied from Docker: account 3 `open_positions=1` |
| 21:06:05 | **Closed in MT5** (mobile, reason 1), 1.30785, profit +187.53, entry commission −3.99 | MT5 exit deal 197043764 (read-only check) |
| 21:14 | `native_pg.py switch --force` (owner) | PowerShell Operational log |
| 21:15:16–22 | start.bat; the worker started both terminals hidden and read them ~10 ms after connect: **0 deals, 0 positions** on both accounts; trade 30 not in the fetched set → stayed open; snapshot empty → Home «ціна недоступна» | worker.log, sync_log 21:15 |
| 21:18:43 | App stopped cleanly through the launcher | api.log/worker.log end, run file removed |
| ~21:21 | Read-only check: first read empty, 3 s later 2 deals of the position, 6 in the window | scratch script (positions_get, history_deals_get only) |

The close was **not** written to Docker: Docker's last sync (20:35) still saw the position open.

## Docker-only data after 16:19 UTC

Row diff Docker vs native (before Docker was stopped): trades 30 = 30, trade_exit_deals identical,
only trade 30's `excursion_at` and sync fields differed. **0 trades and 0 closes exist only in
Docker.** The 36 Docker sync_log rows were copied into native (new ids, verified; backup
`backups/pre-synclog-merge-native-20261120T205018Z.dump`).

## Root fix (merge 8a6088b)

- `sync.read_trading`: every DB-open position that `positions_get` does not report is read by
  position id (`history_deals_get(position=)`, no time window) and built by the normal builder,
  so its close, exit deals, P&L, costs, exit reason and MAE/MFE come from the usual path.
- A terminal that looks cold (no window deal, no position) while such a position's history is
  empty is read again (2 s pause, at most 4 reads). A warm terminal is never waited for.
- Still no full close (no history, entry only, partial close): the trade stays open, a warning
  is logged, the next sync retries; «Головна» shows «Не вдалося підтвердити закриття» instead of
  live values — only when the snapshot entry comes from the account's latest successful sync
  (`_synced_at` per account in `open_positions.json`).
- Tests: `test_sync_reconcile.py` (closed while away, cold terminal, stays cold, warm without
  history, entry-only, partial close), `test_home_api.py`, `test_open_positions_snapshot.py`,
  `HomePage.test.tsx`.

## Repair of trade 30

No hand-written SQL: the first sync after start.bat on the merged code reads the position by
id and closes it. Result to be confirmed after the owner's restart.

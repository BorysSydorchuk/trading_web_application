# M8-10b reconciliation: November P&L and «Ліміти» (2026-11-20)

Data: dev DB `trading_journal` (trades synced from MT5, read-only), Home API and the stored monthly digest, read 2026-11-20 ~09:40 Brussels.

## B. November P&L: Home +1 444 USD / +4.8 % vs digest +1 457.57 / 7.29 %

Accounts: «FN Stellar Lite 2-Step» (passed), «FN Stellar Funded», «FN Stellar Funded 2», each account size 10 000 USD. Money = net P&L (gross + commission + swap) of trades closed in November, by close time in Brussels.

| # | Trade | Account | Symbol | Closed (Brussels) | Gross | Commission | Swap | Net P&L | Excluded | Home (account money) | Digest (strategy) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | FN Stellar Lite 2-Step | EURUSD | 02.11 09:39 | 264.04 | -3.22 | -6.20 | 254.62 |  | 254.62 | 254.62 |
| 2 | 7 | FN Stellar Lite 2-Step | GER40 | 03.11 08:15 | -214.85 | 0.00 | -6.05 | -220.90 |  | 33.72 | 33.72 |
| 3 | 8 | FN Stellar Lite 2-Step | GER40 | 03.11 14:33 | 266.42 | 0.00 | 0.00 | 266.42 |  | 300.14 | 300.14 |
| 4 | 9 | FN Stellar Lite 2-Step | EURUSD | 04.11 10:39 | 207.90 | -5.39 | 0.00 | 202.51 |  | 502.65 | 502.65 |
| 5 | 10 | FN Stellar Lite 2-Step | GBPUSD | 04.11 13:14 | 0.00 | -14.00 | 0.00 | -14.00 |  | 488.65 | 488.65 |
| 6 | 11 | FN Stellar Lite 2-Step | GBPUSD | 04.11 13:33 | -7.20 | -6.30 | 0.00 | -13.50 |  | 475.15 | 475.15 |
| 7 | 12 | FN Stellar Lite 2-Step | EURUSD | 05.11 10:35 | -100.10 | -7.70 | 0.00 | -107.80 |  | 367.35 | 367.35 |
| 8 | 13 | FN Stellar Lite 2-Step | EURUSD | 06.11 04:30 | -104.40 | -4.20 | -8.08 | -116.68 |  | 250.67 | 250.67 |
| 9 | 14 | FN Stellar Lite 2-Step | XAUUSD | 09.11 20:42 | 310.96 | -0.59 | 0.00 | 310.37 |  | 561.04 | 561.04 |
| 10 | 17 | FN Stellar Funded 2 | XAUUSD | 11.11 14:00 | -13.00 | -0.95 | 0.00 | -13.95 | yes | 547.09 | 561.04 |
| 11 | 15 | FN Stellar Funded | XAUUSD | 11.11 15:32 | 427.44 | -0.95 | 0.00 | 426.49 |  | 973.58 | 987.53 |
| 12 | 16 | FN Stellar Funded | GBPUSD | 12.11 09:34 | -106.56 | -10.08 | 0.00 | -116.64 |  | 856.94 | 870.89 |
| 13 | 18 | FN Stellar Funded | GER40 | 12.11 15:40 | 8.23 | 0.00 | 0.00 | 8.23 |  | 865.17 | 879.12 |
| 14 | 19 | FN Stellar Funded | GER40 | 12.11 16:08 | -104.41 | 0.00 | 0.00 | -104.41 |  | 760.76 | 774.71 |
| 15 | 20 | FN Stellar Funded | EURUSD | 13.11 13:47 | 240.00 | -8.75 | 0.00 | 231.25 |  | 992.01 | 1005.96 |
| 16 | 21 | FN Stellar Funded | GER40 | 13.11 16:17 | 7.60 | 0.00 | 0.00 | 7.60 |  | 999.61 | 1013.56 |
| 17 | 23 | FN Stellar Funded | GBPUSD | 16.11 14:30 | -104.72 | -9.52 | 0.00 | -114.24 |  | 885.37 | 899.32 |
| 18 | 24 | FN Stellar Funded | GBPUSD | 16.11 17:12 | 13.65 | -6.37 | 0.00 | 7.28 |  | 892.65 | 906.60 |
| 19 | 22 | FN Stellar Funded | GBPUSD | 17.11 02:25 | 214.80 | -4.20 | -1.79 | 208.81 |  | 1101.46 | 1115.41 |
| 20 | 25 | FN Stellar Funded | EURUSD | 17.11 11:07 | -104.04 | -10.71 | 0.00 | -114.75 |  | 986.71 | 1000.66 |
| 21 | 26 | FN Stellar Funded | GER40 | 18.11 15:33 | 209.21 | 0.00 | 0.00 | 209.21 |  | 1195.92 | 1209.87 |
| 22 | 27 | FN Stellar Funded | GER40 | 19.11 16:37 | 247.70 | 0.00 | 0.00 | 247.70 |  | 1443.62 | 1457.57 |

| | Home (before fix) | Digest «Усі рахунки» (before fix) |
|---|---|---|
| Trades | 22 (incl. 1 excluded) | 21 (strategy only) |
| Net P&L | 1 443.62 (shown +1 444) | 1 457.57 |
| % base | 30 000 (3 accounts with a trade) | 20 000 (accounts with a strategy trade) |
| % | 4.81 % | 7.29 % |

Why they differ:
- **The difference is 13.95 USD, not 13.57.** 13.57 = 1 457.57 − the rounded 1 444. The cause is trade 17 (XAUUSD, «FN Stellar Funded 2», −13.95, excluded from statistics, M8-01). Home counts it as account money; the digest leaves it out of the strategy numbers. The digest already showed it in «Виключені угоди» (account total 1 443.62), but without a %.
- **20 000 vs 30 000:** the digest base counted only accounts with a *strategy* trade. «FN Stellar Funded 2»'s only November trade is the excluded one, so its 10 000 dropped out of the digest base. Home counted it.

Fix (one shared definition, `backend/app/domain/period_base.py`, used by Home, Home charts and digests):
- **% base:** one account selected → its size. All accounts → the sum of the sizes of the non-archived accounts with at least one trade closed in the period, **excluded trades included**.
- **Money:**
  - Account views (Home hero, charts, limits, today) include excluded trades.
  - The digest stays a strategy view: 1 457.57, now / 30 000 = 4.86 %.
  - Its «Виключені угоди» block shows the account total with the same base: 1 443.62 / 4.81 %. This is exactly Home's number.
- **Test:** Home month == digest month (account total) for all accounts and for one account.
- **Stored digests keep their old numbers until «Оновити».**

## C. «Ліміти» vs MT5 account data (2026-11-20 ~09:42 Brussels)

Source:
- **Balance and equity:** MT5 `account_info`, stored by the worker in `accounts.balance` / `accounts.equity`, synced 09:41.
- **Period P&L:** trades synced from MT5 deal history.
- **Start balance** = balance − net P&L closed since the period start (Brussels).
- **Result** = (equity − start balance) / account size.

| Account | Period | Start balance | Equity | Result % | Home (before fix) | Difference |
|---|---|---|---|---|---|---|
| FN Stellar Funded | day | 10 327.62 | 10 327.62 | 0.0000 | 0.0000 | 0.0000 |
| FN Stellar Funded | week | 9 883.61 | 10 327.62 | 4.4401 | 4.4401 | 0.0000 |
| FN Stellar Funded | month | 9 431.09 | 10 327.62 | 8.9653 | 8.9653 | 0.0000 |
| FN Stellar Funded 2 | day | 9 978.49 | 10 056.25 | 0.7776 | 0.0000 | −0.7776 |
| FN Stellar Funded 2 | week | 9 978.49 | 10 056.25 | 0.7776 | 0.0000 | −0.7776 |
| FN Stellar Funded 2 | month | 9 992.44 | 10 056.25 | 0.6381 | −0.1395 | −0.7776 |

**Bug (> 0.05 %):** Home counted closed trades only. The open GBPUSD position (floating +77.76 = equity − balance) was missing.

Fix:
- Each bar is now (closed in the period + floating) / size.
- Floating = equity − balance from the last balance sync, if it is not older than 5 min. Otherwise Home uses closed only, and `floating_included: false`.
- `to_daily_stop_pct` follows the new day %.
- The rules engine and the «СТОП» banner are unchanged: they still use closed trades only (M8-01 decision).
- Tests: fresh, stale, and no open position.

Known small difference (LOW): MT5 takes the entry commission from the balance at open, so the day % is slightly high until the trade closes (about 0.04 % on a 1-lot forex trade).

**Still to check:** the raw MT5 deal history (`history_deals_get`), for balance operations not in the trades table. «FN Stellar Funded 2»: the stored start balance 9 986.05 is 6.39 below the balance implied by its trades. It runs read-only after 16:00 Brussels, so it can't clash with the worker's MT5 connections in trading hours. The result is added here.

## PM corrections (2026-11-20, tier S, merge `1d15eaf`)

- **Digest layout:** the line «Разом по рахунках (з виключеними)» now sits under the strategy result. The «Виключені угоди» block lists only the excluded trades.
- **All 5 saved digests recomputed:** backup `backups/pre-migration-recompute-digests-20261120T101536Z.dump`.
  - Numbers changed in 4 of them.
  - Week 09–15.11: 3.81 % → 2.54 %. The base is now 30 000, because the excluded XAUUSD trade on 11.11 brings in «FN Stellar Funded 2».
  - Week 26.10 and October: switched to the new journal taxonomy breakdowns, the breakeven rule, and the excursion / excluded blocks.
  - Week 16–22.11: gained `account_net_pnl_pct`.
  - November was already current.
- **AI summaries:** weeks 09.11 and 16.11 and October now show «Підсумок застарів». Week 16.11 got the mark only because the new % field was added, not because a number changed. Review texts are unchanged.

## C. MT5 deal history «FN Stellar Funded 2» (2026-11-20 ~11:45 Brussels, read-only `history_deals_get` + `account_info`)

| Time (UTC) | Deal | Type | Profit | Commission | Running balance |
|---|---|---|---|---|---|
| 10.11 12:53 | 194830322 | balance (deposit) | 10 000.00 | 0 | 10 000.00 |
| 11.11 12:59 | XAUUSD 0.13 in | sell | 0 | −0.95 | 9 999.05 |
| 11.11 13:00 | XAUUSD out | buy | −13.00 | 0 | 9 986.05 |
| 20.11 07:33 | GBPUSD 1.08 in (still open) | sell | 0 | −7.56 | 9 978.49 |
| 20.11 09:05 | XAUUSD 0.07 in | sell | 0 | −0.45 | 9 978.04 |
| 20.11 10:36 | XAUUSD out | buy | −96.46 | 0 | 9 881.58 |

The deals add up exactly to the MT5 balance 9 881.58, so there is no unknown balance operation and no sync gap.

The 6.39 = 13.95 − 7.56 came from two things:
- **The stored «starting_balance» 9 986.05 (not our bug):**
  - It is the balance when the account was added to the journal, after trade 17. So «start + closed trades» counted trade 17 (−13.95) twice.
  - The real start is the 10 000.00 deposit, which is also the account size (`reference_balance` 10 000). Every % uses the account size, so no % was affected. Correct it in Settings if wanted.
- **Entry commission of the open GBPUSD trade (−7.56): our bug.**
  - MT5 takes it from the balance when the trade opens. It is in no closed trade, and equity − balance does not include it.
  - So «Ліміти» showed the day 7.56 too high: 0.0756 %, over the 0.05 % threshold.
  - Fix: each bar now also adds the cash an open trade has already booked (its net P&L so far: entry commission, partial exits). This is counted in the period when the trade opened.
  - Test: the real case.

After the fix («Ліміти» vs MT5, 11:47 Brussels):

| Period | MT5 start balance | Equity | MT5 result | Home | Difference |
|---|---|---|---|---|---|
| day | 9 986.05 | 9 988.50 | 0.0245 % | 0.0245 % | 0 |
| week | 9 986.05 | 9 988.50 | 0.0245 % | 0.0245 % | 0 |
| month | 10 000.00 (deposit 10.11) | 9 988.50 | −0.1150 % | −0.1150 % | 0 |

«FN Stellar Funded»: unchanged, 0 difference, no open trade.

Known limitation: a partial exit of an open trade that happens in a later period than the trade's open is counted in the open period, not on the day of the partial exit. Rare. Fix later if needed by attributing exit deals by deal time (BACKLOG).

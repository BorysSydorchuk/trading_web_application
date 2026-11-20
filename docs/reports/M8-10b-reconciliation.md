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

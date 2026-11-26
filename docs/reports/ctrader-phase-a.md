# cTrader integration, phase a: connect, accounts, balance and equity

Firm (PM 2026-11-26): the cTrader account is a **KeyFunding** account, not FundedNext; its firm rules are in `config/firms.yaml` (docs/reports/keyfunding-firm-rules.md).

Tier L. Owner request 2026-11-23 (STEP 2). Branch `ctrader/integration`, base `main` 608871b.

## What was built

- **Account platform.** `accounts.platform` is `mt5` or `ctrader`, with cTrader columns
  (`ctid_trader_account_id`, `ctrader_is_live`). Migration `f1a2b3c4d5e6` (down revision
  `e7c41b9a2d60`). The login/server uniqueness is now a partial index for MT5 only. The migration
  is applied by the next app start, which makes a backup first.
- **Read-only by construction.** `app/ctrader/guard.py` has an allowlist of payload types. Trading
  messages (new, amend, cancel and close order, among others) raise before anything reaches the
  socket. Tests check the allowlist, the transport write path and a source scan for direct socket
  writes. OAuth asks only for scope `accounts`, and the token response must say `accounts`.
- **Client.** Own asyncio JSON-over-WebSocket client (`websockets`, owner OK, DECISIONS 2026-11-23).
  It handles the heartbeat, reconnects with backoff, rate limits (50 req/s, 5 req/s historical),
  `retryAfter`, the live or demo host per account, and token refresh with a 1 h cool-down after a refused
  refresh.
- **Tokens.** These are stored in a gitignored file in DATA_DIR and written atomically. They are never logged,
  and the `websockets` logger is quieted. CTRADER_CLIENT_ID/SECRET come only from `.env`.
- **API.** `GET /api/ctrader/status`, `POST /api/ctrader/connect`, `GET /api/ctrader/callback`,
  `GET/POST /api/ctrader/accounts`, `DELETE /api/ctrader/connection` (docs/api.md).
- **Worker.** A balance/equity job runs on the MT5 cadence, capped at 45 s per run. Equity is
  balance + the net unrealized P&L. It is read as trader, then P&L, then trader, and kept only when both balances
  match. Results go to `sync_log`, so the status bar and the Home figures use the same data as MT5.
- **UI.** Settings → «Рахунки» → «Додати рахунок» → choose the platform → «Підключити cTrader» →
  OAuth in the browser → pick the accounts → save with the size and firm rules. The status bar shows the
  platform per account, and cTrader errors appear in Ukrainian («Підключіть cTrader знову» when the
  token is invalid). On Home, the «Ліміти» card shows the exact «Баланс» and «Еквіті» of the
  account, with «дані застаріли» when the sync is older than 5 min.

## Tests

- Recorded, sanitized fixtures only. No live cTrader calls in tests.
- About 310 cTrader and migration tests, plus the MT5 isolation tests (MT5 sync, margin and backfill skip
  cTrader accounts). Home API +2 tests, HomePage +3 tests.
- Full gate: see the merge commit message.

## Reviews

database-reviewer APPROVE (MEDIUM: UNIQUE login/server, fixed as a partial index). security-reviewer
APPROVE with MEDIUMs (fixed or in BACKLOG). python-reviewer CHANGES REQUESTED: fixed in b16cb90.
code-reviewer: see the merge commit.

## Known limits, needing the first live check

- Not run against live cTrader yet. Still unconfirmed: the heartbeat JSON body, the token
  response shape, the `permissionScope` field, a demo token on the live host, `moneyDigits` on
  this broker, equity versus the platform figure, and the unit of `retryAfter`.
- Redirect URI `http://localhost:8000/api/ctrader/callback`. The API binds 127.0.0.1, so
  `localhost` must resolve to IPv4 on this machine.
- A process restart while a refreshed token pair is still unsaved loses that pair, and the owner reconnects.
- No deals, trades or positions from cTrader yet (phase b). There is no calculator, margin or MAE/MFE for
  cTrader yet (phase c). The calculator margin text for a cTrader account is the generic MT5 one.
- BACKLOG: Windows ACL on the token file, side effects of `GET /accounts`, deposit asset check.

## Owner steps

1. Add the two lines to `.env.example` (blocked for the agent) and real values to `.env`:
   `CTRADER_CLIENT_ID=`, `CTRADER_CLIENT_SECRET=`.
2. The redirect URI in the Open API app must be exactly `http://localhost:8000/api/ctrader/callback`.
3. Restart the app (the migration and its backup run then).

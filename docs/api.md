# API contract

Base URL: `/api` (backend `http://127.0.0.1:8000`, proxied by Vite in dev).
JSON only. All timestamps are ISO 8601 UTC with `Z` suffix. Decimal values (money, prices, volumes, percentages) are JSON **strings**, e.g. `"1234.50"`. IDs are integers.

## Errors

Any non-2xx response has this body:

```json
{ "error": { "code": "db_unavailable", "message": "Database is not reachable", "details": null } }
```

- `code`: stable snake_case identifier. The frontend maps it to Ukrainian text in `uk.ts` (`errors.<code>`), else shows `errors.unknown`.
- `message`: English, for logs and developers.
- `details`: optional object (for example validation errors: `{ "fields": { "name": "required" } }`).

Known codes: `validation_error` (422, `details.fields` maps field path → English message), `not_found` (404), `method_not_allowed` (405), `conflict` (409), `bad_request` (400), `unauthorized` (401), `forbidden` (403), `service_unavailable` (503, non-DB), `db_unavailable` (503), `config_error` (500, broken config/*.yaml; `details: {file, problems[]}`), `internal_error` (500), `http_error` (other). Backend raises custom codes via `app.errors.ApiError`.
Unhandled exceptions are logged with a traceback to `logs/` and returned as `internal_error`; the API never returns an HTML error page.

## M0

### GET /api/health

Always `200` while the API process is up (status bar uses it; "API unreachable" is a network failure on the client side).

```json
{
  "status": "ok",
  "version": "0.1.0",
  "time_utc": "2026-10-31T15:00:00Z",
  "db": { "ok": true, "latency_ms": 3, "error": null }
}
```

- `status`: `"ok"` when every check passes, `"degraded"` otherwise.
- `db.ok=false` → `db.error` holds a short English reason (no credentials, no connection string).
- DB check is `SELECT 1` with a 2 s timeout.

Status bar mapping: API reachable + `status=ok` → green; API reachable + `degraded` → red with "БД недоступна"; network error → red with "Сервер недоступний". Poll every 15 s.

## M1

Conventions: list endpoints return `{ "items": [...] }` (plus `"total"` when paginated). Datetimes are UTC ISO with `Z`; the UI converts to Europe/Brussels. Decimal fields are strings or `null`.

### Accounts (PRD 6.1)

- `GET /api/accounts?include_archived=false` → `{ "items": Account[] }` (sorted by name)
- `POST /api/accounts` body `AccountInput` → `201 Account`
- `GET /api/accounts/{id}` → `Account`
- `PATCH /api/accounts/{id}` body: any subset of `AccountInput` → `Account`
- `DELETE /api/accounts/{id}` → `204`. If the account has trades it is archived (`status="archived"`), otherwise deleted.

`AccountInput` (required unless marked):
```json
{
  "name": "FN Stellar P1", "firm": "FundedNext", "program": "Stellar 2-Step",
  "phase": "phase_1", "login": 12345678, "server": "FundedNext-Server",
  "terminal_path": "D:\MT5\fn-p1\terminal64.exe",
  "starting_balance": "100000.00", "currency": "USD",
  "status": "active",
  "reference_balance": null,
  "daily_loss_pct": "5.00", "max_drawdown_pct": "10.00", "profit_target_pct": "8.00"
}
```
Optional: `terminal_path`, `status` (default `active`), `reference_balance`, the three `*_pct`.
`phase`: `phase_1 | phase_2 | funded`. `status`: `active | passed | failed | archived`. `currency`: 3 letters.
Errors: `409 conflict` (`details.field` = `name` or `login`) for a duplicate name or login+server; `422 validation_error`.

`Account` = `AccountInput` + read-only:
```json
{
  "id": 1,
  "password_env_key": "MT5_PASSWORD_12345678",
  "password_configured": true,
  "balance": "100512.30", "equity": "100498.10", "balance_synced_at": "...",
  "server_offset_hours": 2,
  "created_at": "...", "updated_at": "..."
}
```
The investor password is never sent through the API. It lives in `.env` under `MT5_PASSWORD_<login>`; `password_configured` says whether that key is set.

### Sync status (PRD 6.2)

- `GET /api/sync/status` → one row per non-archived account:
```json
{ "items": [ {
  "account_id": 1, "account_name": "FN Stellar P1",
  "state": "ok",
  "last_attempt_utc": "...", "last_success_utc": "...",
  "error_code": null, "error_message": null,
  "server_offset_hours": 2, "open_positions": 0
} ] }
```
`state`: `ok` (last attempt succeeded), `error` (last attempt failed), `running`, `never` (no sync yet), `stale` (last success older than 3 × the expected interval: the worker is probably not running).
`error_code` (worker side): `password_missing`, `terminal_not_found`, `terminal_start_failed`, `login_failed`, `timeout`, `mt5_error`, `internal_error`. `error_message`: short English text; the UI shows Ukrainian text via `uk.ts` `sync.errors.<code>`.

### Trades

- `GET /api/trades` → `{ "items": TradeRow[], "total": 123 }`
  Query: `account_id` (repeatable), `symbol` (repeatable), `status` (repeatable), `from`, `to` (ISO date or datetime; filter on `close_time`, open trades on `open_time`), `sort` (any TradeRow field among: `open_time`, `close_time`, `symbol`, `net_pnl`, `r_multiple`, `risk_pct`, `volume`, `session`, `status`; default `close_time`), `order` (`asc|desc`, default `desc`), `limit` (1–500, default 100), `offset`.
- `GET /api/trades/{id}` → `TradeDetail`
- `PATCH /api/trades/{id}` body `{ "initial_sl": "2650.50" }` → `TradeDetail`. M1 accepts only `initial_sl` (and only when status is `needs_sl`, or to correct it later). Recomputes risk/R/planned RR/violations; `needs_sl` → `needs_description`. Journal fields come in M2.
- `GET /api/inbox/counts` → `{ "needs_sl": 0, "needs_description": 3, "draft": 1 }`
- `GET /api/trades/symbols` → `{ "items": ["EURUSD", "XAUUSD"] }` (distinct symbols, for filters)

`TradeRow`:
```json
{
  "id": 10, "account_id": 1, "account_name": "FN Stellar P1", "position_id": 50123,
  "symbol": "XAUUSD", "direction": "buy", "status": "needs_description",
  "open_time": "2026-11-02T08:15:03Z", "close_time": "2026-11-02T09:01:44Z", "duration_seconds": 2801,
  "entry_price": "2650.12000000", "exit_price": "2661.40000000", "volume": "0.50000000",
  "initial_sl": "2645.00000000", "last_sl": "2645.00000000", "tp": "2668.00000000",
  "commission": "-3.50", "swap": "0.00", "gross_pnl": "564.00", "net_pnl": "560.50",
  "pnl_pct": "0.5605", "balance_at_open": "100000.00", "risk_amount": "256.00", "risk_pct": "0.2560",
  "r_multiple": "2.1895", "planned_rr": "3.4922",
  "session": "london", "weekday": 0, "hour": 9, "is_reentry": false,
  "violations": ["min_planned_rr"]
}
```
`TradeDetail` = `TradeRow` + `exit_deals: [{ticket, time, price, volume, profit, commission, swap, reason}]`, `rule_violations: [{rule_key, source, details}]`, `initial_sl_source` (`deal|order|position|user|null`), and the journal fields (null in M1).

### Journal field definitions (PRD 6.4)

- `GET /api/journal-fields` → `{ "fields": JournalField[] }` in form order:
```json
{ "key": "setup_context", "label": "Контекст (Flow H1 / H4)", "type": "enum",
  "options": [ { "value": "yes", "label": "так", "deprecated": false } ],
  "required": true, "analytics": true, "storage": "column", "allow_other_text": false }
```
`type`: `enum | multi_enum | bool | int | text | links | auto`. `storage`: `column` (real trade column) or `extra` (JSONB `trades.extra`).
Optional attributes: `text_key` (companion free-text column; with `allow_other_text: true` it applies only to the `other` option, otherwise it is an optional note for any value), `min`/`max` (int fields). `rule_violations` is `multi_enum` whose options are the rules.yaml rule keys. `chart_links` is `links`; `required` means at least one `before` link. `bias_alignment` is `auto` (not required until the bias module exists).

### Rules config

- `GET /api/rules` → `{ timezone, sessions: [{name, start, end, entries_allowed}] (sorted by start), sync, broker_time, rules: {key: {enabled, value?, ...}} }`; decimals as strings, counts as ints.

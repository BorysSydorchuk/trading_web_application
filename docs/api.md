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

Known codes: `validation_error` (422, `details.fields` maps field path → English message), `not_found` (404), `method_not_allowed` (405), `conflict` (409), `bad_request` (400), `unauthorized` (401), `forbidden` (403), `service_unavailable` (503, non-DB), `db_unavailable` (503), `internal_error` (500), `http_error` (other). Backend raises custom codes via `app.errors.ApiError`.
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

## M1 (draft, refined at the start of M1)

### Accounts (PRD 6.1)
- `GET /api/accounts` → `{ "items": Account[] }`
- `POST /api/accounts` → `Account` (201)
- `GET /api/accounts/{id}` → `Account`
- `PATCH /api/accounts/{id}` → `Account`
- `DELETE /api/accounts/{id}` → 204 (sets status `archived`, trades are kept)

```json
{
  "id": 1, "name": "FN Stellar P1", "firm": "FundedNext", "program": "Stellar 2-Step",
  "phase": "phase_1", "login": 12345678, "server": "FundedNext-Server",
  "terminal_path": "C:\\MT5\\fn_p1\\terminal64.exe",
  "starting_balance": "100000.00", "currency": "USD", "status": "active",
  "reference_balance": null,
  "rules": { "daily_loss_pct": "5.00", "max_drawdown_pct": "10.00", "profit_target_pct": "8.00" },
  "password_ref": "MT5_PASSWORD_FN_P1",
  "created_at": "...", "updated_at": "..."
}
```
`phase`: `phase_1 | phase_2 | funded`. `status`: `active | passed | failed | archived`. `password_ref` names a key in `.env`; the password itself never travels through the API.

### Sync status (PRD 6.2)
- `GET /api/sync/status` → `{ "items": [ { "account_id": 1, "last_attempt_utc": "...", "last_success_utc": "...", "ok": false, "error_code": "terminal_not_running", "error_message": "...", "server_offset_hours": 2 } ] }`

### Trades
- `GET /api/trades?account_id=&symbol=&from=&to=&status=&sort=close_time&order=desc&limit=50&offset=0` → `{ "items": Trade[], "total": 123 }`
- `GET /api/trades/{id}` → `Trade` with `exit_deals`, `violations`, `chart_links`.
- `PATCH /api/trades/{id}` → set `initial_sl` (for `needs_sl`) and journal fields (M2).
- `GET /api/inbox/counts` → `{ "needs_sl": 0, "needs_description": 3, "draft": 1 }`

### Journal field definitions (PRD 6.4)
- `GET /api/journal-fields` → `{ "fields": [ { "key": "setup_context", "label": "Контекст сетапу", "type": "enum", "options": [...], "required": true, "analytics": true, "storage": "column" } ] }`

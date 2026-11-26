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

Known codes: `validation_error` (422, `details.fields` maps field path → English message; optional `details.field_codes` maps field path → stable code for the few field errors the UI shows specific text for, see Accounts), `not_found` (404), `method_not_allowed` (405), `conflict` (409), `bad_request` (400), `unauthorized` (401), `forbidden` (403), `service_unavailable` (503, non-DB), `db_unavailable` (503), `config_error` (500, broken config/*.yaml; `details: {file, problems[], reason?}`; `reason: "mojibake"` = the file's text is garbled by a wrong-encoding re-save, M3-15; absent for other problems), `internal_error` (500), `http_error` (other). M2 adds: `journal_incomplete` (422, `details.missing[]`), `needs_sl` (409, from `PUT .../journal` and `POST .../extract`), `trade_open` (409, M1), `ai_not_configured` (503), `ai_error` (502, `details.kind`). Backend raises custom codes via `app.errors.ApiError`.
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

M7-02 adds `backup_target` (opaque SHA-256 database-scope identity, or null for an
unsupported backup target) and `backups` (the status object below). The worker's
loopback-only health probe checks `status`, `db.ok` and matching `backup_target` before
each dump; it does not trigger AI or MT5. Backup failures do not change DB health.

### GET /api/backups/status (M7-02)

Read-only, no database query, archive scan, restore, manual dump or mutation.
The same object is included in `/api/health` for the existing status-bar poll.

```json
{
  "state": "ok",
  "last_success_at": "2026-11-15T17:00:00Z",
  "last_failure_at": null,
  "last_error_code": null,
  "error_code": null,
  "overdue": false,
  "attempts": 1,
  "failed_attempts": 0,
  "next_due_at": "2026-11-16T17:00:00Z",
  "retry_at": null
}
```

- `state`: `ok | running | failed | overdue`; `overdue` independently means the latest
  Brussels 18:00 slot has not completed, including while a catch-up is running.
- `last_success_at`: UTC creation time of the last successfully verified scheduled
  archive; it appears only after publication/reconciliation, not when dumping starts.
- `attempts`: attempts for the latest claimed slot (max 3); `failed_attempts`: persisted
  cumulative failure events, including interrupted/retention/integrity failures.
  Historical `last_failure_at` and `last_error_code` survive success.
- `retry_at`: next allowed retry after a failed attempt; null after exhaustion or a
  corruption/retention error requiring inspection. The worker checks every 15 seconds.
- Error codes: `dependencies_unhealthy`, `backup_failed`, `interrupted`,
  `state_unavailable`, `retention_failed`, `worker_unavailable`, `archive_invalid`,
  `backup_locked`. Only allowlisted codes reach UI; no path, URL, credential or raw error.
- Worker state becomes stale after 2 minutes without checks (35 minutes for a running
  dump, allowing the existing dump and two inspection timeouts). The last known success
  remains visible. Corrupt/inaccessible state returns a safe status object with
  `state_unavailable`; it does not break normal API health.
- All dates are UTC; frontend formats full date/time in Europe/Brussels. No writable
  backup endpoint or new authentication model; existing localhost-only architecture.

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
`terminal_path`: blank = not set; otherwise must end in `terminal64.exe` and must **not** be under Program Files (MT5_SETUP.md step 1). Rejected: `C:\Program Files\…`, `C:\Program Files (x86)\…`, the 8.3 names `C:\PROGRA~1`/`C:\PROGRA~2`, and wherever `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramW6432%`, `%ProgramFiles(Arm)%` point on the server machine; case-insensitive, `/` or `\`, repeated separators, `.`/`..`, surrounding quotes and `%VAR%` expansion are normalised first. Not rejected: lookalikes such as `C:\Program Files Backup\…`, `D:\Program Files\…`, `C:\MT5\Program Files\…`. The value is stored as sent (not expanded). Response for POST and PATCH:
```json
{ "error": { "code": "validation_error", "message": "Request validation failed",
  "details": { "fields": { "terminal_path": "the terminal must not be under C:\\Program Files; … (docs/MT5_SETUP.md step 1)" },
               "field_codes": { "terminal_path": "terminal_in_program_files" } } } }
```
`details.field_codes` is present only when at least one field has a stable code; today the only one is `terminal_in_program_files`. Other field errors have only `details.fields`.

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

- `GET /api/sync/status` → one row per active account (`status=active`). Passed, failed and archived accounts are not synced by the worker, so they are not listed:
```json
{ "items": [ {
  "account_id": 1, "account_name": "FN Stellar P1",
  "state": "ok",
  "last_attempt_utc": "...", "last_success_utc": "...",
  "error_code": null, "error_message": null,
  "server_offset_hours": 2, "open_positions": 0
} ] }
```
`state`: `ok` (last attempt succeeded), `warning` (last attempt succeeded but something needs attention, e.g. `error_code=positions_skipped` with the details in `error_message`), `error` (last attempt failed), `running`, `never` (no sync yet), `stale` (latest attempt older than 3 × the expected interval, whatever its outcome: the worker is probably not running or hung; the latest error stays in error_code/error_message).
`error_code` (worker side): `positions_skipped` (warning only), `password_missing`, `terminal_not_found`, `terminal_in_program_files` (saved terminal_path is under Program Files; the worker refuses to start it, MT5_SETUP.md step 1), `terminal_start_failed`, `login_failed`, `timeout`, `mt5_error`, `internal_error`. `error_message`: short English text; the UI shows Ukrainian text via `uk.ts` `sync.errors.<code>`.

### Trades

- `GET /api/trades` → `{ "items": TradeRow[], "total": 123 }`
  Query: `account_id` (repeatable), `symbol` (repeatable), `status` (repeatable), `from`, `to` (ISO date or datetime; filter on `close_time`, open trades on `open_time`), `sort` (any TradeRow field among: `open_time`, `close_time`, `symbol`, `net_pnl`, `r_multiple`, `risk_pct`, `volume`, `session`, `status`; default `close_time`), `order` (`asc|desc`, default `desc`), `limit` (1–500, default 100), `offset`.
- `GET /api/trades?missing_r=true` (2026-11-14): only closed trades with `r_multiple` null; combines with the other filters (the digest «Сума R» n/N link uses it with account and from/to of the period).
- `GET /api/trades/{id}` → `TradeDetail`
- `PATCH /api/trades/{id}` body `{ "initial_sl": "2650.50" }` → `TradeDetail`. Accepts only `initial_sl` (and only when status is `needs_sl`, or to correct it later). Recomputes risk/R/planned RR/violations; `needs_sl` → `needs_description`. Journal fields are saved with `PUT /api/trades/{id}/journal` (M2).
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
`TradeDetail` = `TradeRow` + `exit_deals: [{ticket, time, price, volume, profit, commission, swap, reason}]`, `rule_violations: [{rule_key, source, details}]`, `initial_sl_source` (`deal|order|position|user|null`), and the journal fields (null in M1; in M2 they move into `journal`, see "TradeDetail in M2").

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


## M2

Everything journal-related is driven by `config/journal_fields.yaml`: no field list in code. "YAML field" below means a field `key` from that file; "YAML key" means a field `key` or a `text_key`.

### TradeDetail in M2

`TradeDetail` keeps everything from M1 except the journal: the top-level journal columns (`setup_context` … `quality_rating`, `poi_type_other`, `emotion_*_text`, `bias_alignment*`) and `extra` are **replaced** by one object `journal`. These stay top-level: `raw_text`, `transcript`, `ai_filled_fields`, `described_at`. New: `chart_links`, `missing_required`.

```json
{
  "...": "TradeRow + exit_deals + rule_violations + initial_sl_source as in M1",
  "journal": { "setup_context": "yes", "poi_type": "other", "poi_type_other": "OB H4",
               "followed_plan": true, "quality_rating": 4,
               "rule_violations": ["min_planned_rr", "max_risk_pct"], "bias_alignment": null },
  "chart_links": [ { "id": 3, "url": "https://www.tradingview.com/x/AbCd1234/", "kind": "before",
                     "preview_url": "https://s3.tradingview.com/snapshots/a/AbCd1234.png" } ],
  "raw_text": "...", "transcript": null, "ai_filled_fields": ["setup_context"],
  "described_at": "2026-11-03T10:00:00Z",
  "missing_required": ["fvg_kind", "chart_links"]
}
```
- `journal` has every YAML key (fields and `text_key`s, `column` and `extra` storage) except `type: links` fields (links are only in `chart_links`); `null` when empty (also an empty `multi_enum` and `rule_violations` with no violations). Values: `enum` → string, `multi_enum` → array, `bool`, `int`, text → string.
- `journal.rule_violations` = all rule keys on the trade (auto + user), sorted; the source of each is in `TradeDetail.rule_violations[]` (`{rule_key, source, details}`).
- `journal.bias_alignment` = effective value (`bias_alignment_override` ?? `bias_alignment`), read-only in M2 (bias module comes later).
- `missing_required`: what blocks `complete` right now (same rule as the save below). Order = YAML order; `chart_links` when no `before` link.
- `chart_links[].preview_url`: for a snapshot link → `https://s3.tradingview.com/snapshots/<first char of id, lowercase>/<id>.png`; `null` for chart links (the UI shows the plain link).
- `extra` keys that are no longer in the YAML are not shown in `journal` but are kept in the DB.

### Journal save (PRD 6.4, 6.5)

- `PUT /api/trades/{id}/journal` body `JournalInput` → `TradeDetail`
```json
{
  "fields": { "setup_context": "yes", "poi_type": "other", "poi_type_other": "OB H4",
              "emotion_before": "calm", "followed_plan": true, "quality_rating": 4,
              "rule_violations": ["max_risk_pct"] },
  "chart_links": [ { "url": "https://www.tradingview.com/x/AbCd1234/", "kind": "before" } ],
  "raw_text": "опис угоди як є",
  "ai_filled_fields": ["setup_context", "emotion_before"],
  "complete": false
}
```
- **Top level:** all five keys are required (`raw_text` may be `null`); unknown top-level keys → 422 `validation_error`.
- **`fields`:** keys = YAML keys, except `type: auto` (e.g. `bias_alignment`) and `type: links` (`chart_links`). Any other key (unknown, or `auto`/`links`) → 422 with `details.fields["fields.<key>"]`.
  - Full replacement **of the keys currently defined in the YAML**: a YAML key missing from `fields`, or `null`, is cleared. `trades.extra` keys that are not in the YAML are kept as they are.
  - Types: `enum` → option `value` string; `multi_enum` → array of option values, no duplicates; `bool` → `true`/`false`; `int` → JSON integer within `min`/`max`; text fields and `text_key`s → string, trimmed, ≤ 5000 chars, empty → `null`.
  - Deprecated options: rejected as new values, accepted when the trade already stores that same value.
  - `text_key` with `allow_other_text: true` (e.g. `poi_type_other`): only allowed when its enum is `other`; otherwise it is cleared (saved as `null`, no error).
  - `storage: column` → trades column; `storage: extra` → `trades.extra[key]`.
  - `rule_violations` (the user's confirmed list):
    - a key that is not an auto violation on the trade → stored as a `source=user` violation; a user violation missing from the list is deleted;
    - auto violations are never deleted or duplicated by this endpoint: an auto key missing from the list is ignored (the UI shows auto entries as locked); an auto key in the list keeps the auto row and creates no user row.
- **`chart_links`:** full replacement, 0–10 items, no duplicate URLs (compared as lower-case scheme + host, path **as-is** (ids are case-sensitive) with exactly one trailing slash; query and fragment ignored; backend and frontend use the same rule; the later duplicate gets the error). Saving replaces links, so link ids change on every save. `kind`: `before | after` (`bias` → 422). URL rule (backend and frontend use the same regex):
  - `^https://([a-z0-9-]+\.)?tradingview\.com/(x/[A-Za-z0-9]+/?|chart(/([A-Za-z0-9]+/?)?)?)(\?[^#\s]*)?(#\S*)?$` (matched after lower-casing scheme and host only; the path is case-sensitive, so `/X/<id>` is rejected);
  - i.e. snapshot `/x/<id>` with optional trailing slash, or chart `/chart` with an optional trailing slash and optional layout id; query and fragment allowed; ≤ 500 chars.
  - Errors: 422 with `details.fields["chart_links.<i>.url"]` / `["chart_links.<i>.kind"]`.
- **`raw_text`:** `null` or a string ≤ 20000 chars, stored in `trades.raw_text`.
- **`ai_filled_fields`:** keys the AI filled and the user did not change (the UI keeps this list). Keys that are not in `fields` with a non-null value are ignored.
- **`complete`:**
  - `false` → status `draft`.
  - `true` → every `required: true` YAML field must be non-null; a `text_key` with `allow_other_text` is required when its enum is `other`; at least one `before` chart link when `chart_links` is required. Otherwise 422 `journal_incomplete` with `details: { "missing": [...] }` (same keys/order as `missing_required`) and nothing is saved.
- **Status rules:** allowed from `needs_description`, `draft`, `complete`. `needs_sl` → 409 `needs_sl` (set the initial SL first). Open trade → 409 `trade_open`. Saving `complete: false` on a complete trade moves it back to `draft`.
- `described_at` is set on the first successful save and updated on every later save.
- The worker sync never changes `status` (once `draft`/`complete`), journal fields, `raw_text`, `ai_filled_fields`, user violations or chart links.

### AI extraction (PRD 6.5)

- `POST /api/trades/{id}/extract` body `{ "text": "..." }` (1–20000 chars; unknown keys → 422) → `ExtractResult`. Saves nothing except the usage log; the UI puts the result into the form and the user saves with `PUT .../journal`.
```json
{
  "fields": { "setup_context": "yes", "entry_model": "ifvg_m5", "lesson": "..." },
  "ai_filled_fields": ["setup_context", "entry_model", "lesson"],
  "missing_required": ["poi_type", "fvg_kind", "chart_links"],
  "dropped": [ { "key": "exit_reason", "reason": "evidence_not_in_text" } ],
  "usage": { "model": "claude-sonnet-5-5", "fallback_used": false, "input_tokens": 1830,
             "output_tokens": 210, "cost_usd": "0.0058", "duration_ms": 4200 }
}
```
- Allowed for trades in `needs_description`, `draft`, `complete`. `needs_sl` → 409 `needs_sl` (the UI shows the SL form first); open → 409 `trade_open`.
- The extraction schema is generated from the YAML. Fillable: `enum`, `multi_enum` (except `rule_violations`), `bool`, `int`, `text`, and `text_key`s. Never filled by the model: `auto`, `links`, `rule_violations`.
- `fields` contains only keys the model filled and that survived the guards; `missing_required` is computed by the server from these `fields` (extraction never returns links, so `chart_links` is listed whenever it is required; links in the text are not detected). Text fields and `text_key`s must be Borys's own words: the value has to appear verbatim in the input text.
- **Guards** (server side, after the model answers; each removed value is listed in `dropped` with its `reason`):
  - `evidence_not_in_text`: every value must come with an `evidence` quote that appears in the input text (case-insensitive, whitespace-normalised);
  - `invalid_option`: enum values must be valid, non-deprecated options; `out_of_range`: ints within `min`/`max`;
  - `parent_not_other`: a `text_key` with `allow_other_text` is dropped when its enum was not filled as `other`;
  - `parent_not_selected` (M8-04..08): a `show_if` field (or its `text_key`) is dropped when its parent includes the option neither in the answer nor in the trade's saved journal;
  - `question`: a text value containing `?` while its evidence does not;
  - `not_fillable`: a key the model returned that is not in the schema (auto, links, `rule_violations`, unknown) is dropped;
  - the output has no free-form message field, so the model cannot ask questions.
- **Model:** `ANTHROPIC_MODEL_EXTRACTION` (default `claude-sonnet-5-5`). On overload (529), 5xx, connection error or timeout, after the SDK's own retries, one attempt on `ANTHROPIC_MODEL_FALLBACK` (default `claude-opus-5-5`); the whole call stays within the 30 s target. Never on refusal. `usage.model` is the model that answered.
- **Errors** (all logged to `logs/api.log`; every AI attempt also to `logs/ai_usage.jsonl` — `ai_not_configured` makes no AI call, so it has no usage line). The UI shows `uk.ts` `errors.<code>`; for `ai_error` it shows `errors.ai_error_kinds.<kind>`, falling back to `errors.ai_error`:
  - `503 ai_not_configured`: `ANTHROPIC_API_KEY` empty. The manual form still works.
  - `502 ai_error` with `details.kind`: `auth` | `rate_limit` | `overloaded` | `timeout` | `connection` | `api` | `refusal` | `invalid_output`. `refusal` is logged at ERROR as a prompt bug.
  - `409 needs_sl` / `409 trade_open`; `404 not_found`; `422 validation_error`.

### AI usage

- Every AI call (success or failure) appends one JSON line to `logs/ai_usage.jsonl`:
  `{ "ts": "...Z", "purpose": "extract", "trade_id": 10, "requested_model": "...", "model": "<model that answered, or null>", "fallback_used": false, "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": "0.0058" | null, "ok": true, "error_kind": null, "duration_ms": 4200 }`
  - Append-only plain file append, **not** the rotating log handler and never rotated (the monthly total is read from it).
  - No input text, no output values, no key in this file. Fallback = two lines (one per attempt).
- Prices per million tokens live in `config/ai_pricing.yaml` (`input`, `output`, `cache_write`, `cache_read` per model id). Unknown model → `cost_usd: null` and a WARNING log.
- `GET /api/ai/usage` → `{ "month": "2026-11", "cost_usd": "0.1234", "calls": 12, "failed_calls": 1, "unpriced_calls": 0, "input_tokens": 0, "output_tokens": 0, "configured": true, "extraction_model": "claude-sonnet-5-5" }`.
  - `calls` / `failed_calls` count attempts (lines), not user actions: a fallback is 2 calls.
  - Month = current Europe/Brussels calendar month (by `ts`). Lines with `cost_usd: null` are not in `cost_usd` and are counted in `unpriced_calls`; the UI then shows that the total is incomplete.
  - Broken lines in the file are skipped with a WARNING (never a 500).
  - Settings shows the month-to-date cost, the model and whether the key is set.

## M3

### Voice notes (PRD 6.5, ROADMAP M3)

`AudioNote`:
```json
{ "id": 5, "trade_id": 10, "bias_note_id": null,
  "status": "pending", "progress": null, "duration_seconds": "118.400",
  "mime_type": "audio/webm", "transcript": null,
  "error_code": null, "created_at": "2026-11-05T09:10:00Z", "transcribed_at": null,
  "file_url": "/api/audio/5/file" }
```
- `status`: `pending` (queued) → `processing` → `done` | `failed`. `progress`: JSON number (not a decimal string), 0.0–1.0 while `processing` (transcribed audio seconds / duration), `1.0` when `done`, else `null`.
- `error_code` (only when `failed`; the UI shows `uk.ts` `errors.transcription.<code>`; the English detail is only in `logs/worker.log`):
  `audio_unreadable` (file can't be decoded) | `audio_missing` (file gone from disk) | `no_speech` (nothing recognised) | `model_unavailable` (model can't be loaded/downloaded) | `timeout` (> 600 s of work) | `transcription_failed` (anything else).
- `duration_seconds`: from the decoded audio (worker); `null` until known.

Endpoints:
- `POST /api/trades/{id}/audio`: raw audio bytes as the request body (no multipart). `Content-Type`: `audio/webm`, `audio/ogg`, `audio/mp4`, `audio/mpeg`, `audio/wav` (parameters like `;codecs=opus` are ignored) → `201 AudioNote` (`pending`).
  - Errors: empty body → 422 `validation_error`; other type → 415 `unsupported_media_type`; > 25 MB → 413 `audio_too_large`; unknown trade → 404; open trade → 409 `trade_open`. Any closed status (also `needs_sl`) is allowed.
  - The file is written to `<DATA_DIR>/audio/YYYY/MM/<uuid>.<ext>` **before** the row is inserted; it is never deleted by the app (also not when transcription fails).
- `GET /api/audio/{id}` → `AudioNote` (the UI polls it about every second while `pending`/`processing`).
- `GET /api/audio/{id}/file` → the stored audio bytes with the stored `Content-Type` (replay). 404 `audio_missing` when the file is gone.
- `POST /api/audio/{id}/retry` → `AudioNote` back to `pending` (progress, error and transcript cleared). Only from `failed`; otherwise 409 `audio_not_failed`.
- `TradeDetail.audio_notes`: `AudioNote[]`, oldest first.
- The API never transcribes. The worker job `transcription` (every 2 s, one note at a time, oldest `pending` first, claimed with `FOR UPDATE SKIP LOCKED`) runs faster-whisper; `processing` notes left by a stopped worker go back to `pending` when the worker starts.
- The transcript is not copied into the trade by the server. The UI appends it to the description text box (editable), and the user runs `POST /api/trades/{id}/extract` on the text as in M2. `trades.raw_text` (saved with the journal) is the final text.

Settings (`.env`): `WHISPER_MODEL` (default `small`), `WHISPER_COMPUTE_TYPE` (`int8`), `WHISPER_LANGUAGE` (`uk`; empty = auto-detect), `WHISPER_BEAM_SIZE` (1), `WHISPER_CPU_THREADS` (`auto` = physical core count, detected once; 0 = library default; or a number 1–256), `WHISPER_VAD_FILTER` (`true`: bundled Silero VAD skips silence), `WHISPER_CONDITION_ON_PREVIOUS_TEXT` (`true`: the previous window's text primes the next one, keeps Latin terms through long notes), `WHISPER_TEMPERATURES` (`0.0,0.4`: comma-separated, ascending, each 0–1; `0` = no temperature fallback), `DATA_DIR` (default `data` in the repo root). Glossary for `initial_prompt` in `config/transcription.yaml` (`glossary: [...]`), reloaded on change like the other config files.

### Transcript normalization (M3, PM 2026-11-05)

`config/transcript_glossary.yaml` (UTF-8, reloaded on change like the other config files):
```yaml
replacements:
  - to: FVG
    from: [ФВГ, фвг]
  - to: FVG H1
    from: [FVH1]
  - to: IFVG
    from: [ІФВГ, ИФВГ, іфввг]
  - to: H4
    from: [Н4]        # Cyrillic Н
```
- Matching is case-insensitive and on word boundaries (no letter/digit/underscore, Cyrillic or Latin, right before/after: "ФВГшка" stays); longest `from` first; one pass. `to` is inserted as written. The worker logs the number of replacements per note at INFO (never the text).
- Applied by the worker to the transcript when a note becomes `done`; `AudioNote.transcript` is the normalized text (the UI shows it in the editable text box as before).
- Validation: `replacements` list (≤ 200), each `to` non-empty, `from` non-empty list of unique non-empty strings with at least one letter or digit (values are stripped; case variants of one `from` under the same `to` are allowed); the same `from` (case-insensitive) under two `to` is an error; mojibake is refused like every config file. Broken file → transcript stored unnormalized + ERROR in worker.log (the note is still `done`). Checked at API and worker start.

### AI key status (M3, PM 2026-11-05)

- `GET /api/health` gets `"ai": { "state": "ok" | "invalid_key" | "not_configured" | "unreachable" | "checking", "checked_at": "<UTC ISO>" | null }`. `status` stays based on the DB only.
- `GET /api/ai/usage` gets the same `"key_state"` value (Settings).
- `POST /api/ai/check` → re-checks now (blocking, ≤ 10 s) and returns the `ai` object.
- States: `not_configured` = no key in env/.env; `checking` = check running (start); `ok` = `models.retrieve` succeeded; `invalid_key` = 401/403 (also set when an extraction gets an auth error); `unreachable` = timeout / connection / 5xx (re-checked automatically every 5 min while unreachable).
- Details (M3-17): `checking` only until the first check ends (a re-check keeps the previous state until it finishes); `checked_at` = end of the last check (or of the extraction auth error), `null` for `not_configured`/first `checking`. Any other API answer (e.g. 404 unknown model id, 429) means the key was accepted → `ok` with a WARNING in api.log. A POST while a check is running waits for that check instead of starting a second call.
- UI: status bar shows an AI chip only when the state is not `ok`/`checking`: "AI: ключ недійсний" / "AI: ключ не задано" / "AI: немає звʼязку"; Settings → AI shows the state with a "Перевірити ключ" button (POST /api/ai/check). A new key still needs an app restart (settings are cached).

### Number words (M2 follow-up)

The number words accepted for `int` values move from code to `config/extraction.yaml`:
```yaml
number_words:
  1: [один, одна, одиниця, единица, единичка, one]
  ...
```
Same matching rules as M2 (whole words, after normalisation, ё → е; words in the file are normalised on load, multi-word phrases allowed). A word may not mean two different numbers. An `int` value is kept only when it is the only number said in its evidence (a denominator of "4 з 5" does not count): "4 або 5", "four or five", "4 - 5" → left empty. Broken file → `config_error` like the other config files (extract: 500 `config_error` with `details.file: "extraction.yaml"`, before any AI call).

### New required fields (M2 follow-up)

- The server remembers when each field became `required: true` (table `journal_field_requirements`: `key`, `required_since` UTC). The first time the table is filled, every field that is required at that moment gets `required_since = 1970-01-01` (applies to all trades). Later: a field that becomes required gets `now()`; a field that stops being required loses its row.
- A required field counts for a trade only when `trade.close_time >= required_since`. This applies to `missing_required` (read, journal save `complete`, extraction) for every status. Complete trades are never downgraded.
- `TradeDetail.missing_new_fields`: keys (YAML order) that are required now, empty on this trade, and were made required after it closed. Informational only, never blocks saving.
- `GET /api/trades?missing_new_fields=true`: only closed trades with a non-empty `missing_new_fields`. The Journal filter is "Неповні за новими полями". Combines with the other filters, sort and pagination (`total` counts filtered trades). `false`/absent = no filter; FastAPI boolean parsing applies (`1/yes/on` = true, `0/no/off` = false), anything else → 422. With `true` a broken journal_fields.yaml → 500 `config_error`.
- Boundary: `close_time == required_since` counts. Open trades: `missing_new_fields` is `[]`. The `allow_other_text` rule (text required when the enum is `other`) is not affected. The table syncs on every journal read/save/extract and every 60 s in the worker, no restart needed; a broken YAML leaves it untouched.

### AI warm-up (M2 follow-up)

The worker keeps `<DATA_DIR>/ai_warmup.json` (`{schema_hash, model, at}`). When the API key is set and the hash of the extraction schema generated from `journal_fields.yaml` (with the model id) differs from the stored one, the worker runs one extraction on a fixed short text in the background. That call is logged in `logs/ai_usage.jsonl` with `"purpose": "warmup"`, `"trade_id": null`. A failed warm-up is logged and retried at most once an hour; it never affects the API. Only the extraction model is warmed, not the fallback model.

Time-based warm-up (M4-02, PM 2026-11-05): the server's compiled grammar expires 24 h after last use, so the same warm-up call also runs (a) once at worker start when the last successful AI call is more than 20 h ago or there is none (latest `ts` of a line in `logs/ai_usage.jsonl` with `ok: true` and no `error_kind`, any purpose except `bias_*` (another schema), or `at` in `ai_warmup.json`, whichever is later), and (b) Mon–Fri at 07:30 Europe/Brussels while the worker runs (cron job `ai_warmup_daily`; if the worker was asleep or stopped then, and it is more than 30 min late, that day is skipped, never fired late). Several reasons at the same moment (schema changed, stale at start, 07:30) make one call. Same call, purpose `warmup`, priced and counted in the month-to-date cost; skipped without an API key, and after a failure the 1 h backoff applies to every reason. A successful warm-up rewrites `ai_warmup.json` (new `at`).

## M4

### Bias config (`config/bias.yaml`, UTF-8, reloaded on change, checked at API/worker start)
```yaml
symbols:                      # order = UI order
  - { symbol: EURUSD, aliases: [євро, евро, фібер, fiber, euro] }
  - { symbol: GBPUSD, aliases: [фунт, кабель, cable, pound] }
  - { symbol: XAUUSD, aliases: [золото, gold, голд] }
  - { symbol: GER40,  aliases: [дакс, DAX, GER] }
reminders:                    # Europe/Brussels, weekdays only
  pre_london: { from: "07:45", until: "11:00" }
  pre_ny:     { from: "12:30", until: "16:00" }
```
`GET /api/bias/config` → `{ symbols: [{symbol, aliases}], reminders: {...}, kinds: ["pre_london","pre_ny","weekly","monthly"] }`. Broken file → 500 `config_error` like the other configs.

### Bias notes and entries (PRD 6.6)
A **bias note** is one input (text and/or voice) for one `kind` + `period_date`; it holds one **entry per symbol**.
- `period_date` (Brussels date): the trading day for `pre_london` / `pre_ny`; the Monday of the week for `weekly`; the 1st of the month for `monthly`. The API normalizes any date inside the week/month to that day.
- Unique: one note per `kind` + `period_date`; one entry per note + symbol.

`BiasNote`:
```json
{ "id": 3, "kind": "pre_ny", "period_date": "2026-11-06", "raw_text": "...",
  "entries": [ BiasEntry, ... ],            // config symbol order
  "audio_notes": [ AudioNote, ... ],        // oldest first, same AudioNote as M3 (trade_id null, bias_note_id set)
  "created_at": "...Z", "updated_at": "...Z" }
```
`BiasEntry`:
```json
{ "id": 7, "symbol": "XAUUSD", "direction": "bullish",   // bullish | bearish | neutral | no_trade
  "key_levels": "2650 POI FVG H1", "narrative": "...", "confidence": 2,   // 1..3 or null
  "chart_links": [ { "id": 1, "url": "...", "kind": "bias", "preview_url": "..." } ],
  "was_correct": null, "was_correct_source": null,   // true/false + "manual" after Borys marks it
  "ai_filled_fields": ["direction", "key_levels"] }
```

Endpoints:
- `GET /api/bias/notes?from=YYYY-MM-DD&to=YYYY-MM-DD&kind=...` → `{ items: BiasNote[] }` newest period first (default: last 30 days).
  - Filters `period_date` inclusive (a weekly note is listed by its Monday, a monthly one by the 1st). Default `to` = today (Brussels), `from` = `to` − 29 days; only `from` given → `to` = `from` + 29. `from` after `to` → 422 `details.fields.from`. `kind` may repeat (`kind=pre_ny&kind=weekly`). Same date: pre_ny, pre_london, weekly, monthly.
- `GET /api/bias/notes/{id}` → `BiasNote`. `GET /api/bias/notes/by-period?kind=pre_ny&date=2026-11-06` → `BiasNote` or 404 (date normalized for weekly/monthly).
- `POST /api/bias/notes` body `{ kind, period_date, raw_text?, entries: [BiasEntryInput] }` → 201 `BiasNote`; 409 `bias_note_exists` (with `details.id`) if one exists for kind + period.
  - `entries` is required but may be `[]` (create the note first, then upload its voice and fill entries with PUT). `period_date` must be a `"YYYY-MM-DD"` string. Strict JSON like the journal (`"2"` is not a confidence, unknown keys → 422).
- `PUT /api/bias/notes/{id}` same body (kind/period_date may change, 409 on clash) → `BiasNote`. Entries are replaced by symbol: symbols not in the list are deleted. A kept symbol keeps its entry `id`, and `was_correct` / `was_correct_source` unless its `direction` changed (then both are cleared); its fields and chart links are replaced (link ids change).
- `DELETE /api/bias/notes/{id}` → 204 (entries, links and audio rows cascade; audio files stay on disk like M3).
- `BiasEntryInput`: `{ symbol (must be in bias.yaml), direction (required), key_levels?, narrative?, confidence? (1..3), chart_links?: [{url}] (TradingView rule from M2, kind "bias"), ai_filled_fields?: [...] }`. Errors 422 with `details.fields["entries.<i>.<field>"]`; duplicate symbol → `entries.<i>.symbol` (the later one); symbol not in bias.yaml (exact name) → `entries.<i>.symbol`; duplicate link (M2 rule) → `entries.<i>.chart_links.<j>.url`. Text fields trimmed, empty → null, ≤ 5000 chars. `ai_filled_fields` ⊆ direction / key_levels / narrative / confidence; fields without a value and repeats are dropped. A broken bias.yaml or rules.yaml → 500 `config_error` on every write, nothing saved.
- `PATCH /api/bias/entries/{id}/result` body `{ was_correct: true | false | null }` → `BiasEntry` (source `manual`; null clears).
- Voice: `POST /api/bias/notes/{id}/audio` → 201 `AudioNote` (same rules as `POST /api/trades/{id}/audio`, same queue, same normalization; unknown note → 404); `GET/POST /api/audio/{id}…` unchanged. The UI appends the transcript to the note's text box as on Describe.
- Every create / update / delete of a note recomputes `bias_alignment`, `bias_alignment_weekly`, `bias_alignment_monthly` of the affected closed and open trades (symbol by prefix, see DECISIONS) in the same transaction. `bias_alignment_override` is never changed.

### Bias extraction
- `POST /api/bias/notes/extract` body `{ kind, text }` → `{ entries: [{ symbol, fields: { direction?, key_levels?, narrative?, confidence? }, evidence: {...} }], dropped: [...], usage: {...} }`. Saves nothing except the usage log. Same rules as trade extraction (M2): structured output, every value with an evidence quote found in the text, no questions, nothing invented, ambiguous → empty; symbols from bias.yaml aliases (a symbol the text does not mention is not returned); `confidence` only from words/digits 1–3 via the number-word rules. Errors as trade extraction (503 `ai_not_configured`, 502 `ai_error`, 422, config_error). Usage log purpose `bias_extract`.
- Prompt `backend/prompts/extract_bias.md` (glossary + aliases injected).
- Details (M4-06):
  - Body: `kind` one of `pre_london | pre_ny | weekly | monthly` (prompt context only), `text` as trade extraction (1–20000 chars, not blank). Strict JSON, unknown keys → 422. Order: body 422 → 500 `config_error` (`bias.yaml`, then `extraction.yaml`) → 503 `ai_not_configured` → AI call. No DB access.
  - Response:
```json
{ "entries": [ { "symbol": "XAUUSD",
                 "fields": { "direction": "bullish", "key_levels": "FVG H1 2648", "confidence": 2 },
                 "evidence": { "direction": "по золоту шукаю покупки", "key_levels": "від FVG H1 2648", "confidence": "впевненість 2" } } ],
  "dropped": [ { "symbol": "EURUSD", "key": "direction", "reason": "symbol_not_in_text" } ],
  "usage": { "model": "claude-sonnet-5-5", "fallback_used": false, "input_tokens": 1500, "output_tokens": 120, "cost_usd": "0.0063", "duration_ms": 2400 } }
```
  - `entries`: bias.yaml order, only symbols with at least one kept value; `fields` keys in the order direction, key_levels, narrative, confidence, absent when not filled; `evidence` has the same keys (the model's quote). `direction` ∈ bullish/bearish/neutral/no_trade; `confidence` integer 1–3; text fields are his own words (≤ 5000 chars): `narrative` one continuous piece of the text; `key_levels` one or more pieces joined by `"; "`, each a verbatim piece of the text, in text order, no repeats (e.g. `"хаю Азії; 18900"`), else dropped (`evidence_not_in_text` / `question` for a bad piece, `invalid_option` for wrong order, a repeat or an empty piece). The UI marks filled fields as `ai_filled_fields` when it saves with `POST/PUT /api/bias/notes`.
  - `dropped`: `{symbol, key, reason}`, sorted by bias.yaml symbol order then field order (unknown symbols last). Reasons as trade extraction (`evidence_not_in_text`, `invalid_option` incl. two different values for one symbol + field, `out_of_range`, `question`, `not_fillable`) plus `symbol_not_in_text`: the symbol's name or one of its bias.yaml aliases is not in the text (whole words, normalised like the evidence; Cyrillic aliases with a stem of ≥ 4 letters also with a case ending: золото → по золоту, кабель → на кабелі; євро only as a whole word). It is checked anywhere in the text, not in the value's quote.
  - "Усі пари" / "everything": a value counts only for symbols the text names; the model gives one item per named symbol (same quote allowed).
  - `usage` = trade extraction `usage`. Usage log line: `purpose: "bias_extract"`, `trade_id: null`. An `auth` error also marks the key `invalid_key` (M3-17). No warm-up for the bias schema: the first bias fill after a bias.yaml symbol change (or after 24 h without a bias call) may take ~25 s. Bias calls do not count as a trade warm-up.

### Bias status (dashboard reminders)
- `GET /api/bias/status` → `{ date: "2026-11-06", weekday: true, now: "...Z",
  sessions: { pre_london: { note_id: 3 | null, missing: true, remind: true, from: "07:45", until: "11:00" },
              pre_ny: { ... } },
  weekly: { note_id | null }, monthly: { note_id | null } }`.
  `remind` = weekday and Brussels now in [from, until) and no note. Used by Головна (cards + "Записати біас") and the sidebar Біас badge (count of `remind: true`), polled every 60 s.

### Trades
- `TradeDetail` and journal list items get `bias_alignment_weekly` and `bias_alignment_monthly` (the effective daily value `bias_alignment` already exists, override wins).
  - Precisely: `TradeRow` (so `GET /api/trades` items and `TradeDetail`) has top-level `bias_alignment` (effective: override ?? auto, same as `journal.bias_alignment`), `bias_alignment_weekly`, `bias_alignment_monthly` (auto only, no override). Values `aligned | counter | neutral_bias | no_bias`, `null` until the trade was first aligned (next sync).
  - `TradeDetail.bias_note_ids: { daily, weekly, monthly }`: id of the note whose entry decided each value (daily: pre_ny or the pre_london fallback), `null` for no_bias (or while bias.yaml / rules.yaml is broken). Use it for the link to the bias note. Journal gets optional columns for weekly/monthly; Describe shows all three next to the auto data with a link to the bias note.


## M5 - Position sizing calculator (implementation contract, 2026-11-07)

PRD 6.8 / ROADMAP M5. This section specifies planned endpoints; M5-02 initially implements only the pure financial core. No trade execution. Financial JSON values are decimal strings; timestamps UTC, displayed with existing Brussels formatting.

### Sizing and validation

- Effective balance = account.reference_balance when configured, otherwise last synced account.balance. Never use starting_balance as an implicit fallback. Return balance source and balance_synced_at (null for reference balance).
- Inputs: exact account-specific broker symbol, buy/sell direction, entry, exactly one of sl_price/sl_points, and exactly one of risk_percent/risk_amount. With neither risk field supplied, default risk_percent is 1. Both specified is invalid. Null is not a substitute for an explicitly supplied numeric value at the API boundary.
- Use actual broker point (not inferred from digits); SL distance in points times point gives price distance. Buy SL below entry; sell SL above entry. Entry/SL positive and on the tick-size grid. No silent alteration of entered prices.
- Loss per lot = abs(entry - SL) / tick_size * tick_value_loss. Loss tick value is in account currency per lot. Require positive finite sizing data. Missing newly captured broker fields requires sync; do not manufacture historic point/loss tick values or change historical trade metrics.
- Risk budget = balance * risk_percent / 100, or risk_amount in account currency. Preserve full Decimal precision through lot selection; fees/slippage are not included in this price-to-SL estimate. Do not reuse rounded historical trade risk to determine volume.
- Numeric resource envelope: core inputs allow at most 64 coefficient digits and Decimal exponents from -64 through 64; working precision is capped at 8192. Reject unsupported representations before arithmetic-context allocation. These technical limits exceed the stored NUMERIC(20,8) data envelope and do not impose a business risk-percent cap.
- Volume = floor(min(budget / loss_per_lot, volume_max) / volume_step) * volume_step. Step is an arbitrary positive Decimal, not a decimal-place count. Require min/max to be positive ordered multiples of step. If rounded volume < minimum, no permissible position: reject rather than increase risk to minimum.
- Actual risk = volume * loss_per_lot; actual risk percent = actual risk / balance * 100. It must not exceed budget. Core outputs retain Decimal precision; serialization/display rounding never feeds lot selection.
- TP targets use SL distance at RR 1.5, 2 and 3, rounded away from entry to a valid tick (up for buys, down for sells). Reject nonpositive sell targets. UI identifies these as target RR; grid rounding may produce a higher actual RR. No existing trading formula is modified.
- Pure core: app.domain.position_size exposes frozen SymbolSpec(point, tick_size, tick_value_loss, volume_min, volume_step, volume_max), PositionSizeRequest(direction, entry, balance, sl_price=None, sl_points=None, risk_percent=Decimal('1'), risk_amount=None), PositionSizeResult(volume, risk_budget, actual_risk, actual_risk_percent, sl_price, sl_distance, tp_1_5, tp_2, tp_3), calculate_position_size(request, spec). Core rejects invalid data with ValueError; API maps errors to readable validation/domain codes. Core money-mode callers explicitly set risk_percent=None.

### Planned endpoints

`GET /api/accounts/{id}/symbol-specs` returns `{items: [...]}` with exact symbol, contract_size, point, tick_size, tick_value_loss, volume_min/step/max, digits, currency_profit/margin and synced_at. Missing account 404; existing account without specs returns empty list.

`POST /api/calculator/calculate` body `{account_id, symbol, direction, entry, sl_price? | sl_points?, risk_percent? | risk_amount?}`. Strict JSON; decimal strings/integers only, no floats/bools/NaN, unknown keys rejected. Account/symbol selection never prefix-matches. Response includes account_id, symbol, direction, entry, effective SL/distance, balance and source/date, risk_budget, volume, actual_risk, actual_risk_percent, tp_1_5/tp_2/tp_3, specs_at and margin metadata. Missing account/spec 404; unusable/missing balance/specs and no permissible minimum volume are visible domain errors. Existing field-error envelope applies.

M5-04c exact shapes (2026-11-09, orchestrator):

- Specs item: `{symbol, contract_size, point, tick_size, tick_value_loss, volume_min, volume_step, volume_max, digits, currency_profit, currency_margin, synced_at}`; decimals as strings, `point`/`tick_value_loss` may be `null` (not yet synced), ordered by symbol.
- Calculate 200: `{account_id, symbol, direction, entry, sl_price, sl_distance, sl_points, balance, balance_source: "reference" | "synced", balance_synced_at, currency, risk_percent, risk_amount, risk_budget, volume, actual_risk, actual_risk_percent, tp_1_5, tp_2, tp_3, specs_at, margin}`. Decimal strings in plain notation (no exponent), full core precision (UI rounds for display). `sl_points` = sl_distance / point; `risk_percent` / `risk_amount`: the one used, the other `null`; `currency` = account currency.
- Calculate errors (envelope `{error: {code, message, details}}`):
  - 422 `validation_error` with `details.fields` (strict JSON, types, unknown keys, both/neither SL, both risk fields, non-positive numbers, numbers outside the core representation limits, `symbol` containing NUL or a UTF-16 surrogate code point; the symbol is never stripped or case-folded). `details.fields` is always an object, `{}` when the core's precision/arithmetic guard names no field.
  - 404 `not_found` with `details.account_id` or `details.symbol` (exact match only).
  - 409 `balance_unavailable`: no reference balance and no synced balance, or the effective balance is not a positive finite number.
  - 409 `specs_incomplete` with `details.missing` (list of spec keys that are null, non-positive or not finite, e.g. `["point", "tick_value_loss"]`): needs a sync.
  - 409 `specs_invalid`: volume limits not ordered / not on the step grid.
  - 422 `invalid_stop`: SL not on the loss side of entry or not positive.
  - 422 `off_tick_grid` with `details.fields` = a **list** of `entry` / `sl_price` (entry first; `sl_price` is the effective SL, also when the input was `sl_points`). Unlike `validation_error`, whose `details.fields` is an object.
  - 422 `below_min_volume` with `details.volume_min` and `details.min_volume_risk` (risk at the minimum volume, account currency): the budget cannot pay for the minimum volume, never rounded up.
  - 422 `invalid_targets`: a sell TP would be ≤ 0.
- The pure core raises `PositionSizeError(ValueError)` with a `code` from the list above (`invalid_stop`, `off_tick_grid`, `below_min_volume`, `invalid_targets`, `specs_invalid`, `validation_error`); existing ValueError behaviour unchanged.

Margin metadata: `{source: cached_estimate | unavailable, amount: string | null, currency, calculated_at, sample_price, sample_volume, reason}`; with `unavailable` every field except `source` and `reason` is `null` (also `currency`); with `cached_estimate` `reason` is `null`. Built from the latest done margin request (see design below). A margin failure never erases a valid sizing result. No sample yields unavailable/no_cached_margin, not zero margin.

`POST /api/calculator/margin-requests` reuses validated sizing input and recomputes rounded volume server-side; returns 202 with request id/status. `GET /api/calculator/margin-requests/{id}` returns pending/processing/done/failed/expired. Exact live result includes source=mt5, amount/currency, entry/volume and UTC time. Frontend discards results for a superseded form state. No API process owns or initializes MT5.

### Margin integration design (PM scope check 2026-11-09, supersedes the 2026-11-07/08 design)

Priority: `POST /api/calculator/calculate` answers from synced `symbol_specs` and the account balance only. It never waits for, calls or depends on MT5 or on a margin request. Margin is secondary and filled in afterwards.

- Frontend: after a successful calculate it posts `POST /api/calculator/margin-requests` (same input) and shows «маржа: обчислюється…» until the request ends. `done` shows the live MT5 margin; `failed`/`expired` shows the estimate from the calculate response with its label, or «маржа недоступна» when there is none. Results for a superseded form state are discarded.
- Worker: one APScheduler job every 2 s handles at most one pending request (oldest first, `FOR UPDATE SKIP LOCKED`), sharing one process-wide lock with the sync job (MT5 talks to one terminal per process; sync keeps priority by holding the lock for its whole cycle). Read-only `order_calc_margin(ORDER_TYPE_BUY|SELL, symbol, volume, entry)` on that account's terminal (existing connect/verify path). Requests not started within 60 s become `expired` (error_code `request_expired`); a terminal/login/MT5 error becomes `failed` with the error code. On worker start, `processing` rows (interrupted) become `failed` (`interrupted`). Timestamps from DB `now()`.
- API de-duplicates: an identical (account, symbol, direction, volume, entry) request already `pending`/`processing` is returned instead of a new row.
- M5-04d exact shapes (2026-11-10, orchestrator):
  - `POST /api/calculator/margin-requests`: body = calculate body (same strict schema). The server runs the same sizing; any calculate error is returned unchanged (same status/code), and then no row is created. On success: 202 with the request item below, `expires_at` = `created_at` + 60 s, currency = account currency. De-dup hit: 202 with the existing item.
  - `GET /api/calculator/margin-requests/{id}`: 200 request item; unknown id 404 `not_found` with `details.id`.
  - POST also returns 422 `validation_error` with `details.fields.entry` / `.volume` when the value does not fit the request table's NUMERIC(20,8) (more than 12 integer digits or 8 decimals; only a 12+ digit entry is reachable today), and no row is created. De-dup is best effort (simultaneous identical POSTs may both insert) and ignores `processing` rows started more than `STALE_PROCESSING_S` (261 s) ago; the worker sweeps those to `failed` / `interrupted` while holding the MT5 lock.
  - Request item: `{id, account_id, symbol, direction, volume, entry, status: pending | processing | done | failed | expired, source: "mt5" | null, amount: string | null, currency, created_at, started_at, finished_at, expires_at, error_code: string | null}`. `source` = `"mt5"` and `amount` set only when `done`; `error_code` set only for `failed` (the `Mt5ErrorCode` value, `interrupted`) and `expired` (`request_expired`). Decimals plain notation. Only the worker changes status: with the worker not running a request stays `pending` (past `expires_at`); the UI stops polling after 75 polls (~75 s) and treats it as expired (shows the estimate or «маржа недоступна»).
  - MT5: `Mt5Source.calc_margin(direction, symbol, volume, price) -> Decimal` on real and fixture sources; `order_calc_margin` joins the read-only allow-list (PRD 6.8 requires it; it only calculates, never places or checks an order). `order_send` / `order_check` / `order_calc_profit` stay forbidden. Result `None` → `Mt5Error` from `last_error()`; a negative or non-finite result → failed `mt5_error`. Fixture source: optional `margins` key `{"<symbol>": {"buy": "<margin per 1.0 lot>", "sell": ...}}`, result = per-lot × volume (price ignored), no entry → `mt5_error` (tests/fixtures/mt5/README.md "Margins").
  - Worker: `app.worker.margin_job.run_margin_cycle(session_factory, source, lock)`; `app.worker.mt5_shared.SharedMt5` holds the process's one Mt5Source and the lock shared with sync.
- Offline estimate (in the calculate response): the latest `done` request for the same account, exact symbol and direction, scaled linearly: `margin * volume / request_volume`, in that request's currency, with `calculated_at`, `sample_price` = its entry and `sample_volume` = its volume. `source: cached_estimate`, labelled in the UI as an estimate with date and price. No `done` request yet: `source: unavailable`, `reason: no_cached_margin`, never zero. A margin failure never erases a valid sizing result.
- Dropped as not needed for this (migration after c8a41e62b903): table `calculator_margin_samples` (the latest done request is the sample) and the `signature` columns (an estimate is keyed by account + exact symbol + direction and always shown dated; spec/leverage changes are not detected, which the label already says). No margin sampling during normal sync.

MetaQuotes sources: [Python margin calculation](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py), [symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants), [margin modes](https://www.mql5.com/en/book/automation/symbols/symbols_margin). order_calc_margin reports hypothetical required margin in account currency excluding existing positions/orders; it is not a free-margin forecast. The cached scaling is an explicitly labelled engineering inference, not a broker guarantee.

### Acceptance evidence

Automated pure-core tests use labelled synthetic examples for all four symbols and edge cases (>=80% position-sizing coverage). They do not satisfy real FundedNext specification acceptance. Borys supplies recorded specs and compares EURUSD/GBPUSD/XAUUSD/GER40 sizing/margin to MT5 within one volume step. No real account operations or unauthorized live calls during development.

### M5-08 Canonical symbols (Borys, M5-07 owner check 2026-11-10)

Problem: FundedNext names the DAX `GER30` (old name), the app uses `GER40`. Canonical names are used in the UI, journal, analytics, bias and rules; broker names only in MT5 calls.

- `config/symbols.yaml` (UTF-8, loader like bias.yaml, reloaded on change, checked at API/worker start):
  ```yaml
  symbols:                      # order = UI order; replaces rules.yaml sync.watch_symbols
    - { name: EURUSD }
    - { name: GBPUSD }
    - { name: XAUUSD }
    - { name: GER40, broker_names: [GER30, GER40.cash, DE40] }
  firms:                        # optional per account.firm override: only these broker names, in this order
    FundedNext: { GER40: [GER30] }
  ```
  Validation: names and broker names unique across the file (case-insensitive), no name/broker name of one symbol is a prefix of another symbol's, firm overrides name known symbols. `bias.yaml` symbols must be canonical names from `symbols.yaml` (config error otherwise).
- Canonical → broker (per account, used by spec sync): candidates = firm override if present, else `[name] + broker_names`; the first candidate the broker has exactly (case-insensitive) wins, else the first broker symbol that starts with a candidate (suffixes like `EURUSD.r`). No match: not found at that broker (sync logs a warning; no spec row).
- Broker → canonical (trades, specs of traded symbols): exact (case-insensitive) name or broker name of any symbol, else the longest name/broker-name prefix, else the broker name itself (unconfigured symbols keep their name).
- DB (migration, backfill copies): `trades.broker_symbol` (NOT NULL; `trades.symbol` = canonical), `symbol_specs.canonical_symbol` (NOT NULL; `symbol_specs.symbol` stays the broker name, unique per account), `calculator_margin_requests.broker_symbol` (NOT NULL; `symbol` = canonical). The canonical names of existing rows are (re)applied from `symbols.yaml` by an idempotent step in the worker at start and at the start of every sync cycle, so stored `GER30` trades show and aggregate as `GER40` and later edits of `symbols.yaml` apply to history too.
- Bias alignment compares the canonical trade symbol with the bias symbol exactly (no prefix match any more). Rules: re-entry by canonical symbol; tick size lookups by broker symbol. trade_check compares MT5 deals with `broker_symbol`. Journal symbol filter/list = canonical.
- Calculator API: `symbol` in calculate / margin-requests bodies = **canonical** name; the spec is found by (account, canonical). Specs list: `{items: [... + broker_symbol], missing: [canonical names from symbols.yaml without a spec row on that account]}`, items in symbols.yaml order then others by name. An account without any spec row (never synced) returns `missing: []` (the UI shows its sync hint instead); several rows with one canonical name show as one item, the row the sync resolver picks for the account's firm (the same row calculate and margin requests use). Margin requests store both; the worker calls MT5 with `broker_symbol`. Cached estimate keyed by canonical symbol.
- UI: option label `GER40 (GER30)` when the broker name differs, `EURUSD` otherwise; `missing` entries shown as disabled options «символ не знайдено у брокера: GER40»; «(потрібна синхронізація)» only for a spec row with null point / tick_value_loss.
- Acceptance: fixture with broker symbol `GER30` (real FundedNext case): trades → `GER40`, spec `GER40 (GER30)`, calculate on `GER40` works, margin request calls MT5 with `GER30`, a GER40 bias aligns with the GER30 trade; an account without any DAX symbol → `missing: ["GER40"]`.

### M5-09 Cross-currency loss value (Borys M5-07 GER40 check FAIL, 2026-11-11)

Problem: for GER30 at FundedNext (profit currency EUR, account USD) MT5 `trade_tick_value` / `trade_tick_value_loss` is 0.12, but real P&L uses the live EURUSD rate: 0.01 × 10 × 1.1091 = 0.11091 USD per tick per lot. The calculator gave 0.13 lot instead of 0.14 (budget 104.02, SL 6460 points).

- Scope: specs whose `currency_profit` differs from the account currency (case-insensitive). Same-currency specs keep `tick_value_loss` unchanged. For cross-currency specs `tick_value` / `tick_value_loss` are never used for sizing or risk any more.
- Loss per tick per lot (account currency) = `tick_size × contract_size × rate`, rate = profit currency → account currency.
- Conversion pair (worker, per account, every sync cycle, for every cross-currency spec): direct pair `<P><A>` (e.g. EURUSD), rate = **ask**; else inverse pair `<A><P>`, rate = 1 / **bid**. Pair lookup at the broker: exact name (case-insensitive) first, else the first broker symbol (sorted) that starts with it and whose next character is not a letter (`EURUSD.r`, `EURUSD#`, `EURUSD-1` yes; `EURUSDT`, `EURUSDm` no); several candidates → first sorted + WARNING (review fix 2026-11-11). Side: a loss in the profit currency is paid by buying that currency, so the higher price is used (conservative, gives the larger loss; bid/ask differ by ~0.001 % on EURUSD). `symbol_select` may be used so the pair gets ticks (read-only, already allowed). No pair or no tick: no rate row is written/updated, WARNING logged.
- Rate time = the pair's `symbol_info_tick().time` converted from broker time to UTC with the account's server offset (PRD 6.3), not the sync time.
- MT5 check (worker, terminal reachable, same sync cycle): `order_calc_profit(ORDER_TYPE_BUY, broker_symbol, 1.0, p, p − N × tick_size)` with p = the symbol's own current ask and N = floor(p × 0.01 / tick_size) ticks (a 1 % move, so the 2-dp rounding of the result is < 0.01 %); `mt5_loss_per_tick` = |result| / N. Profit is linear in volume and price distance, so this equals the check for the user's exact volume/prices (DECISIONS 2026-11-11). `order_calc_profit` joins the read-only allow-list (only calculates). Failure → WARNING, no check value (rate still used).
- Choice: if the check exists and differs from the rate value by > 0.5 % (relative to the rate value), the check value is used (`source: "mt5_check"`) and the worker logs a WARNING with both values; otherwise the rate value (`source: "rate"`).
- DB (migration, database-reviewer, pre-migration backup): table `fx_rates` (id, account_id FK accounts ON DELETE CASCADE, from_currency, to_currency, pair (broker symbol), inverted bool, bid, ask, rate NUMERIC(20,8) > 0, rate_at (UTC), synced_at; unique (account_id, from_currency, to_currency)). `symbol_specs.mt5_loss_per_tick` NUMERIC(20,8) NULL (> 0 when set) and `symbol_specs.mt5_loss_per_tick_at` timestamptz NULL (both NULL or both set). Stored GER30 trades need no data change: all 4 are closed at a price ≠ entry, so their risk already comes from their own P&L (checked 2026-11-11: trade 1 = 167.65 / (136.89 × 0.11) = 0.11133 USD/tick/lot, stored risk 101.05; with 0.12 it would be 108.91).
- Calculator (`POST /api/calculator/calculate` and margin requests, same sizing): cross-currency spec without a rate row → 409 `conversion_rate_unavailable` with `details: {from_currency, to_currency}` (needs a sync; never falls back to tick_value). Response adds:
  - `loss_per_tick`: string, the value used (all specs; same-currency = `tick_value_loss`).
  - `conversion`: `null` for same-currency specs, else `{pair, from_currency, to_currency, rate, side: "ask" | "bid", inverted, rate_at, stale, source: "rate" | "mt5_check", rate_loss_per_tick, mt5_loss_per_tick, mt5_checked_at}`; `stale` = rate_at older than 1 h at calculate time (UTC now); `mt5_*` null when no check.
- Trade metrics fallback (`risk_amount` when nothing was realised at a different price: open, breakeven, tiny move): cross-currency spec → loss per tick from the latest rate row (or the check value by the same 0.5 % rule); no rate → risk `null` (never tick_value). Realised-P&L path unchanged.
- UI (calculator page + Home panel): under the result «курс EURUSD 1.1091 (ask) від <Brussels time>»; stale → warning «Курс старший за 1 год — результат може бути неточним, запустіть синхронізацію»; `mt5_check` → «вартість тіку за MT5: 0.11091 (курс дає 0.11xxx)». Error `conversion_rate_unavailable` → «Немає курсу EUR→USD, запустіть синхронізацію».
- Tests with the real case: tick 0.01, contract 10, rate 1.1091 → 0.11091 USD/tick/lot; buy entry 26478.80 SL 26414.20 (6460 points): budget 104.02 → 0.14 lot, budget 100 → 0.13 lot.

### M5-10 Risk base = account size (PM 2026-11-11, PRD 6.8/6.9)

- `accounts.reference_balance` = account size, labelled «Розмір рахунку» in the UI. Migration (pre-migration backup): `UPDATE accounts SET reference_balance = starting_balance WHERE reference_balance IS NULL`, then NOT NULL (no CHECK, see DECISIONS 2026-11-11 M5-10 tests); pnl_pct only for closed trades (open trades keep NULL, as sync does). `POST /api/accounts`: optional, defaults to `starting_balance`. `PATCH`: may change it, `null` → 422 validation_error (like other required fields). A size so small that a recomputed trade percent would not fit NUMERIC(10,4) → 422 `validation_error` with `details.fields.reference_balance`; a broken rules.yaml → 500 `config_error`; in both cases nothing changes. The same size in another notation (`10000` vs `10000.00`) does not recompute.
- Calculator: the base is always the account size. Response: `balance` = account size, `balance_source` = `"account_size"` (replaces reference/synced), `balance_synced_at` = null; new `current_balance` (string | null; null also when the stored balance is not finite) and `current_balance_synced_at` (UTC | null), information only. `balance_unavailable` only if the stored size is not a positive finite number. UI: «Ризик від розміру рахунку 10 000 USD» next to the budget; «Поточний баланс 10 401.70 USD (від <час>)» as an info line.
- Trades: `risk_pct = risk_amount / account size × 100`, `pnl_pct = net_pnl / account size × 100` (4 dp, ROUND_HALF_UP); `balance_at_open` unchanged and still returned. trade_check tool explains the formula with the account size.
- Rules: `max_risk_pct` uses the new risk_pct; daily/weekly stop % = running closed P&L of the period / account size × 100 (sticky replay unchanged).
- Recompute: the migration recomputes risk_pct/pnl_pct of stored trades in SQL; changing the account size via PATCH recomputes risk_pct, pnl_pct and rule violations of that account's trades in the same transaction; the worker does the same for all accounts once at start (idempotent, small tables; each account in its own savepoint: a failing account is logged at ERROR with its id and skipped, the others are committed). Sync computes new trades with the account size.
- M6 dashboard limits and digests will use the same base (not built yet).
- Tests: balance above (10 401.70) and below (9 857.58) a 10 000 account → 1 % = 100.00 in both; GER40 real case buy 26478.80 / SL 26414.20, 1 % → budget 100.00, lot 0.13 (loss/lot 716.4786); daily stop −3 % = −300.00 regardless of the day's start balance; PATCH size recompute; create default.

## M6 - Dashboard and digests (contract, 2026-11-12)

PRD 6.7, 6.9, 6.10; ROADMAP M6. All percentages are of the account size (`accounts.reference_balance`, PRD 6.8/6.9), never of the current or period-start balance. Symbols are canonical names (`trades.symbol`, M5-08). Periods are Brussels calendar dates (DECISIONS 2026-10-31): week = Monday..Sunday, month = calendar month. Money and R as strings (plain notation, 2 dp money, 4 dp percent/R, ROUND_HALF_UP at the API edge only; Decimal everywhere inside). The UI shows percentages with 2 decimals, format `-0.42%`, on every M6 screen (dashboard and digests); 4 decimals only in the API (PM 2026-11-13). R display in the UI is decided in M6-06.

### Which trades
- Period trades = **closed** trades (`close_time` not null, `net_pnl` not null) whose Brussels close date is inside the period, all accounts that are not archived. Open trades are never in metrics.
- R metrics use only trades with `r_multiple` not null; every R metric returns `{value, n}` with `n` = trades used (UI shows «за 8/10 угод»).

### Metrics (pure, `app/domain/digest_metrics.py`)
- `trades` (count), `wins`, `losses`, `breakeven`: a trade with R and |R| < `breakeven_r_threshold` (config/rules.yaml, default 0.1) is breakeven; otherwise net_pnl > 0 win, < 0 loss, = 0 breakeven (Borys/PM 2026-11-14, DECISIONS). `profit_factor` stays money-based (positive vs negative net_pnl, a breakeven trade's small P&L included).
- `net_pnl` (sum, account currency; all accounts USD today, a mixed-currency set → 409 `mixed_currency`), `net_pnl_pct` = net_pnl / sum of account sizes of the accounts with a trade in the period × 100 (one account: its size).
- `total_r` (sum), `win_rate` = wins / trades × 100 (breakeven is not a win), `avg_win_r` (mean R of wins), `avg_loss_r` (mean R of losses, negative), `expectancy_r` = total_r / n.
- `profit_factor` = sum of positive net_pnl / |sum of negative net_pnl| (money-based, a breakeven-by-R trade's P&L included); null when there is no negative net_pnl.
- `max_drawdown` = largest peak-to-trough fall of running closed net P&L in (close_time, id) order, starting at 0, money and % (same base as net_pnl_pct); 0 when it never falls.
- `best_trade` / `worst_trade`: by net_pnl (ties: earlier close), `{trade_id, symbol, net_pnl, r_multiple, close_time}`.
- Empty period: counts 0, sums "0.00", ratios null.

### Breakdowns
Trade fields: `symbol` (canonical, e.g. GER40), `session`, `hour` (Brussels hour of open), `weekday`, `bias_alignment` (effective = override ?? auto). Journal fields: every field with `analytics: true` in `config/journal_fields.yaml` (in file order; columns and `extra` storage alike), so a new analytic field needs no code change (PM 2026-11-13; replaces the fixed list entry_model, poi_type, followed_plan, emotion_before). Each group: `{key, trades, net_pnl, total_r, win_rate}`; trades with an empty field go to key `null` («не заповнено»). Every journal-field breakdown has `coverage: {filled, total}` (DECISIONS 2026-11-04), shown as «заповнено 34/50».

### Rules and bias sections
- Rules: per `rule_key` `{rule_key, violations, trades, pnl}`; `pnl` = sum of net_pnl of the trades with that violation (signed; a trade with two violations counts in both). Total line: distinct trades with any violation and their net_pnl.
- Bias, separately for `daily` (pre_london + pre_ny entries; trade alignment = effective `bias_alignment`), `weekly` (`bias_alignment_weekly`) and `monthly` (`bias_alignment_monthly`) (PM 2026-11-13): `accuracy` = entries of that kind in the period with `was_correct = true` / entries marked (true or false) × 100, `{value, marked, total}`; P&L, R and trade count of `aligned` vs `counter` trades.

### Norm and deviation
- Norm window: closed trades in the 60 trading days (weekdays Mon–Fri, Brussels) before `period_start`, aligned to the start of its period kind (DECISIONS 2026-11-13); fewer than 60 trading days of history → all history before the period.
- Norm per account and combined (PM 2026-11-13): the digest has `combined` and `by_account[]` metric blocks, each with its own norm from that account's (or all accounts') history. Breakdowns, rules and bias sections are combined.
- The window is cut into periods of the same kind (weeks or months, only periods that have ≥ 1 trade); each metric is computed per period; norm = mean and population standard deviation over those periods.
- Highlight when the period value is worse than mean − k × σ (red) or better than mean + k × σ (green), k = `digest.deviation_sigma` in `config/rules.yaml` (default 1.0). "Better" = higher for net_pnl, net_pnl_pct, total_r, win_rate, avg_win_r, avg_loss_r, expectancy_r, profit_factor; lower for max_drawdown (money and %), and violations count. `trades` is not highlighted.
- Fewer than 20 trading days of history → no highlight, block flag `norm_available: false`, UI «замало історії для норми» (PM 2026-11-13). Trading days are weekdays counted from the first closed trade of that scope to `period_start` (DECISIONS 2026-11-13). Also no highlight with < 3 norm periods or σ = 0, `deviation: null` (technical guard, DECISIONS 2026-11-13).
- Each metric: `{value, norm_mean, norm_sd, deviation: "worse" | "better" | null}`.

### Charts data
- `equity`: per account and combined, points `{time (UTC), cum_pnl}` after each closed trade of the period, starting at 0.
- `r_distribution`: buckets of 0.5 R from the min to the max R (−∞..−3 and 3..∞ folded into the edge buckets), count per bucket.
- `hour_heatmap`: weekday (0–4, plus 5/6 if any) × hour → `{trades, net_pnl}`.
- UI draws them with plain SVG components (no chart library; DECISIONS).

### Digests API
- Stored in `digests` (existing table; unique (kind, period_start)): `metrics` = full snapshot (metrics, breakdowns, rules, bias, norm, charts, `trade_ids`), `generated_at` UTC; review fields `what_worked`, `what_to_fix`, `focus_next`; `ai_summary`. No migration expected; if one is needed it goes through database-reviewer + pre-migration backup.
- `POST /api/digests {kind: "weekly"|"monthly", date: "YYYY-MM-DD"}`: date normalised to the period start (Monday / 1st). Creates (201) or regenerates (200) the snapshot; review fields and ai_summary are kept. A period that has not started → 422 `period_in_future`.
- `GET /api/digests?kind=` → `{items: DigestListItem[]}` newest first: `{id, kind, period_start, period_end, generated_at, trades, net_pnl, net_pnl_pct, total_r, win_rate, reviewed}` (`reviewed` = any review field non-empty).
- M6-06 list (PM 2026-11-13): the list also has **virtual rows** for past periods (weeks and months) that contain at least one closed trade (non-archived accounts, Brussels close date) and have no created digest, from the first closed trade on; periods without trades are not listed. "Past" = the period has started (the current week/month is listed once it has a closed trade). Virtual row: `id: null`, `generated_at: null`, `trades` = closed trade count, `net_pnl` = sum (2 dp string), `net_pnl_pct` / `total_r` / `win_rate` null, `reviewed: false`, `reviewed_at: null`. Created rows add `reviewed_at` (UTC ISO or null). Order: `period_start` desc, created before virtual on the same period (never both). UI badges: «не переглянуто» (reviewed false, also virtual), «переглянуто · <Brussels date of reviewed_at>». Opening a virtual row = `POST /api/digests {kind, date}` (create on demand). No reminder for them (only the latest due unreviewed period, M6-04b).
- `digests.reviewed_at` (timestamptz NULL, migration): set to now when a PATCH leaves at least one review field non-empty and changes a review field; set to null when a PATCH clears all three; regenerate (POST) keeps it. Backfill: digests with a non-empty review get `updated_at`.
- `GET /api/digests/{id}` → full digest; `GET /api/digests/by-period?kind=&date=` → digest or 404.
- `PATCH /api/digests/{id} {what_worked?, what_to_fix?, focus_next?}` (text, max 10 000 chars, `""` → null).
- Next-period bias: the digest page embeds the existing bias note form (`POST/PUT /api/bias/notes`, kind weekly/monthly, date = next period start). The digest response has `next_bias_note_id` (null if none yet).
- `GET /api/digests/suggestion` → `{weekly: {period_start} | null, monthly: {period_start} | null}`: weekly from Friday 16:00 Brussels; monthly from 16:00 on the last trading day (last weekday Mon–Fri) of the month. Per kind only the **latest due period** is suggested, and only while it has no saved review (any of what_worked / what_to_fix / focus_next non-empty); it stays until that review is saved or the next period becomes due (PM 2026-11-13, M6-04 review). The suggestion never walks back to older periods: if the latest period is reviewed there is no reminder, even when older ones are not. Older unreviewed digests show in the «Дайджести» list with the badge «не переглянуто» (`reviewed: false`), no reminder. Only periods from the first closed trade on are suggested. Shown on «Головна» and «Дайджести».
- `POST /api/digests/{id}/ai-summary` (task M6-07, only on button press): one Claude call on `ANTHROPIC_MODEL_SUMMARY` (existing client and usage log, purpose `digest_summary`), input = the snapshot numbers + journal texts (mistakes, lesson, raw text) of the period's trades; output = 3–7 short factual observations in Ukrainian, no advice, no moralising; stored in `ai_summary`. Errors as M2 (`ai_not_configured` / `ai_error`), visible in UI and logs.

### Dashboard API (PRD 6.10)
- `GET /api/dashboard` → `{now, accounts: [...], stop: {today: bool, week: bool}, open_positions: [...], inbox: {needs_sl, needs_description, draft}}`.
- Per active account: `{id, name, currency, account_size, today: {pnl, pct, low_pct, high_pct}, week: {...}, limits: {daily_loss_pct, daily_profit_pct, weekly_loss_pct, weekly_profit_pct}, today_state, week_state}` with state `ok | stop_loss | stop_profit`. P&L = closed trades of the Brussels day / week by close time; low/high = sticky running extremes, the same replay as the rules engine (`_period_stop`, extracted to a shared pure function). Limits from `config/rules.yaml`.
- `stop.today` = any account's today_state ≠ ok → banner «СТОП на сьогодні»; `stop.week` → «СТОП на тиждень».
- Open positions: `{trade_id, account_name, symbol, direction, volume, entry_price, open_time, initial_sl, risk_amount, risk_pct}`.
- M6-03 details (2026-11-13): `today`/`week` = `{pnl, pct, low_pnl, low_pct, high_pnl, high_pct}` (money 2 dp, % 4 dp strings). `limits` values are 4 dp strings (`"-3.0000"`); a stop rule disabled in rules.yaml → that limit is `null` and never stops. An account without a usable size (not finite or ≤ 0) → zero blocks, state `ok`. Open positions sorted by `open_time` ascending (then trade_id); `open_time` ISO UTC; `risk_amount`/`risk_pct` null without SL. `inbox` = `GET /api/inbox/counts` (archived accounts excluded). The endpoint takes `now` via `Depends(utc_now)`.
- Home page: bias status (exists), limits per account with the banner, inbox counts with links, open positions, sync status per account (existing endpoint), links to calculator and describe, digest suggestion.

### Acceptance (ROADMAP M6)
- Fixture week with known trades: win rate, total R, P&L, PF, drawdown match hand calculation (tests), then Borys checks one real week by hand.
- Deviation: fixture history where the week is > 1 σ worse on win rate → red, better on total R → green.
- Review + next week's bias saved from one screen.

## M8-09 - Exit reason from MT5 (PM 2026-11-17)

- Sync stores each closing deal's MT5 DEAL_REASON twice: `trade_exit_deals.reason` (lowercase key: client, mobile, web, expert, sl, tp, so, rollover, vmargin, split, corporate_action, `unknown_<n>`) and `trade_exit_deals.reason_code` (raw integer). Both are NULL when MT5 reports no reason (`reason_code` is also NULL for deals stored before M8-09).
- `trades.exit_reason` is prefilled from the **final** closing deal (max time, then ticket): `sl` -> `sl`, `tp` -> `tp`, `so` -> `stop_out` («стоп-аут», new option). Manual closes (client / mobile / web / expert) stay empty for the owner (fractal update or point B). Only when MT5 reported no reason at all: the final deal price within 1 tick (`symbol_specs.tick_size`) of `initial_sl` or `tp` -> `sl` / `tp`; both or neither -> empty.
- `trades.exit_reason_source`: `mt5_reason` | `price_match` | `owner` | null. The sync writes only when the source is `mt5_reason` / `price_match` (follows a new suggestion, never cleared) or when value and source are both null; the write is a guarded UPDATE so a concurrent owner save wins. `owner` is set by `PUT /api/trades/{id}/journal` whenever the saved exit_reason differs from the stored one (also when cleared); saving it unchanged keeps the source. A value without source (before M8-09) is never touched.
- `TradeDetail.exit_reason_source` (new) and `TradeDetail.exit_deals[].reason_code` (new). The Describe form marks a prefilled exit reason with an «MT5» badge (hint names the source) until the owner changes it; AI extraction never replaces it (it fills only empty or AI-filled fields).
- Backfill: `python -m app.tools.backfill_exit_reason [--apply]` (dry run by default) fills closed trades with empty exit_reason and no source from stored deals, prints counts per source. No MT5 call.

## M8-01 - Exclude a trade from strategy statistics (PM 2026-11-18)

- Schema: `trades.excluded_from_stats` (bool NOT NULL, default false), `trades.excluded_reason` (text), `trades.excluded_at` (timestamptz); CHECK: excluded <=> reason and time set. History table `trade_stats_exclusions` (`id, trade_id -> trades CASCADE, action exclude|include, reason text NULL, created_at, updated_at`), an `exclude` row always has a non-empty reason. The sync never writes these columns, so the flag survives re-sync and partial-close updates; MT5 raw data (deals, prices, P&L) is never changed.
- `POST /api/trades/{id}/exclude {reason: string}` -> `TradeDetail`. Reason trimmed, 1..1000 chars; missing/blank -> 422 `validation_error` (`details.fields.reason`). Already excluded -> 409 `already_excluded`. Unknown trade -> 404. Any status (open included).
- `POST /api/trades/{id}/include {reason?: string | null}` -> `TradeDetail` («Повернути у статистику»). Reason optional (trimmed, max 1000, blank -> null). Not excluded -> 409 `not_excluded`.
- `TradeRow` adds `excluded_from_stats`, `excluded_reason`, `excluded_at`; `TradeDetail` adds `exclusion_history: [{action, reason, at}]` oldest first.
- `GET /api/trades?excluded=true|false`: only excluded / only counted; absent = all (Journal default: all, filter «Показати виключені» on). The inbox list applies the same rule on the client.
- Leaves strategy statistics: inbox counts (`GET /api/inbox/counts`, Home and sidebar badge) and the inbox list for `needs_description` / `draft` (an excluded trade without an initial SL stays in «Потрібен SL»: the risk rules need it), every digest number (combined and per-account metrics, the 60-day norm window, breakdowns, rule section, bias accuracy / aligned vs counter, charts, `trade_ids` and so the AI summary input), digest list rows (created and virtual).
- Stays in money and risk: dashboard today/week P&L, limit states and «СТОП» banners, the rules engine (1 % risk, daily/weekly stops, 10 trades/week, re-entry flags are evaluated over all trades, and the excluded trade keeps its own violations), account balance.
- Digest snapshot adds `excluded: {trades, net_pnl, account_net_pnl, items: [{trade_id, account_id, account_name, symbol, close_time, net_pnl, reason}]}` for the period (all accounts, close time order). `account_net_pnl` = strategy `net_pnl` + excluded `net_pnl` = the accounts' real P&L of the period. Snapshots generated before M8-01 have no `excluded` key. A stored snapshot changes when the digest is regenerated («Оновити») and, since M8-01b, on exclude/include for the trade's week and month.

## M8-02 + M8-03 - Describe an open trade; «до входу» / «після угоди» links (PM 2026-11-18)

- Identity: the sync already creates the trade row of an open position on the first sync (`UNIQUE(account_id, position_id)`, status `open`, `close_time` NULL); partial closes and the final close update that same row. No new table, no migration.
- `config/journal_fields.yaml` field key `phase: before | after` (default before; not allowed for `auto` and `links`). After-trade fields: `exit_reason`, `followed_plan`, `emotion_after` (+ `emotion_after_text`), `mistakes`, `lesson`. `GET /api/journal-fields` returns `phase` on every field.
- `PUT /api/trades/{id}/journal` on an open trade: allowed as a draft; status stays `open`, `described_at` is set. `complete: true` -> 409 `open_trade_complete`. A non-empty after-trade field -> 422 `validation_error` `fields.<key>`; an `after` link -> 422 `chart_links.<i>.kind`. `needs_sl` still -> 409 (closed trade without SL).
- `JournalInput.form_open` (optional bool, default false): the client built the form while the trade was open. If the trade has closed since, the save keeps the stored after-trade values (incl. text keys), their AI markers and the stored `after` links instead of clearing them (so the M8-09 exit-reason prefill and its source survive); everything else is the usual full replacement. Without the flag a closed-trade save is a full replacement as before. The Describe screen fixes the open/closed mode at mount and shows «Угоду щойно закрито…» when the trade closes under it.
- `TradeDetail.missing_required` / `missing_new_fields` of an open trade list pre-entry fields only.
- `POST /api/trades/{id}/extract` on an open trade: the model is offered (schema `key` enum) and may fill pre-entry fields only; `missing_required` pre-entry only. Voice notes (`POST /api/trades/{id}/audio`) are accepted for any status.
- Status on close (`next_status`): an open trade described while open (`described_at` set) closes into `draft` (inbox «Чернетки»), or `needs_sl` without an initial SL (setting the SL then gives `draft`); an undescribed one into `needs_description` as before. `draft`/`complete` are never downgraded. The sync never writes journal fields, `raw_text` or links (only the M8-09 exit-reason prefill of an empty exit reason).
- M8-03 links: `chart_links[].kind` before | after (unchanged contract). Completion still needs at least one `before` link. Describe shows the links in groups: «до входу» (two empty rows by default) and, for a closed trade, «після угоди» (one empty row by default, «додати» for more); empty rows are not sent. Existing links keep their stored kind (chosen by the owner in the per-row select since M2), so no «без позначки» migration (DECISIONS 2026-11-18).

## M8-01b - Saved digests follow exclude / include (PM 2026-11-18)

- `POST /api/trades/{id}/exclude` and `/include` also recompute, in the same transaction, the saved weekly and monthly digests whose period contains the trade's close date (Brussels); one digest row holds the combined and the per-account blocks. Numbers only: `metrics` is rebuilt and `generated_at` = now; review texts and `ai_summary` text are kept. No digest is created; an open trade (no close time) touches none. A recompute error fails the whole request (nothing changed, error shown), like a manual «Оновити».
- Schema: `digests.ai_summary_stale_at` (timestamptz NULL, migration a91d3c7e5f20). Set to the recompute time when the digest has an AI summary and the numbers changed; cleared when a new summary is stored («Оновити підсумок»). `DigestOut.ai_summary_stale_at` (ISO UTC or null). The page shows «Підсумок застарів: дані змінено <дата>».
- Not recomputed: later digests whose 60-day norm window contains the trade (their own period is unchanged); they change on «Оновити».

## M8-15 - Home «Потрібен опис» list; Journal filter by description (PM 2026-11-18)

- `GET /api/trades?described=true|false`: true = the owner saved a journal (`described_at` set, open trades included), false = never saved; absent = all. Journal select «Опис: усі / З описом / Без опису» (URL `described=yes|no`); with status «відкрита» it gives open trades «з описом» / «без опису» (PM condition for keeping status `open`, DECISIONS 2026-11-18).
- `GET /api/trades?archived=false`: leave out trades of archived accounts (default true = all, as before).
- Home «Потрібен опис»: `GET /api/trades?status=needs_description&excluded=false&archived=false&sort=close_time&order=desc&limit=10` (the inbox «Без опису» count rule), polled like the inbox counts (30 s); each row has «Описати» (Describe screen); «Усі N у журналі» links to `/journal?status=needs_description&excluded=hide` when there are more (the Journal itself still shows archived accounts).

## M8-12 - Run without visible windows (PM 2026-11-18)

- `GET /api/system/desktop` -> `{supported, autostart, terminals_visible}` (`supported` = Windows).
- `PUT /api/system/autostart {enabled: bool}` -> same shape; adds / removes the shortcut «Торговий журнал.lnk» in the user's Startup folder (`pythonw scripts/tray.py --autostart`). Error: 500 `shortcut_failed` (message names the cause); 409 `not_supported` off Windows.
- `PUT /api/system/terminals {visible: bool}` -> same shape; stored in `<DATA_DIR>/terminals_visible.json`; the worker job `mt5_windows` (every 3 s) applies it.
- MT5: `RealMt5Source.connect` snapshots the terminal processes at the account's terminal path before `mt5.initialize` and records the new ones (PID + creation time, `<DATA_DIR>/mt5_terminals.json`) after it, also after a failed login or a timeout. Only those are hidden (`ShowWindow SW_HIDE`, re-hidden when restored); «Показати термінали» shows exactly the windows the app hid. A terminal already running before the call (the owner's) is never touched. No MT5 API call changed.
- Desktop: `scripts/tray.py` (pystray) starts `scripts/dev.py --no-browser` with CREATE_NO_WINDOW (children inherit the windowless console), logs to `logs/launcher.log` / `logs/tray.log`, notifies a failed start or crash. `scripts/install_shortcuts.py` writes the icon (`data/journal.ico`), the two desktop shortcuts and autostart (default ON).

## M8-16 - MAE / MFE per trade (PM 2026-11-18; contract)

### Domain (pure, `app/domain/excursion.py`, Decimal only)
- Input: direction (buy/sell), `entry_price`, `initial_sl` (or None), `open_time`, `end_time` (close time, or "now" for an open trade; both aware UTC), price samples `PriceSample(time, bid_high, bid_low, ask_high, ask_low)`. A tick is a sample with high = low.
- Only samples with `open_time <= time <= end_time` count.
- Long (buy) uses **bid**: favourable extreme = max `bid_high`, adverse extreme = min `bid_low`. Short (sell) uses **ask**: favourable = min `ask_low`, adverse = max `ask_high` (the side the position closes on).
- `mfe_distance = max(0, favourable move from entry)`, `mae_distance = max(0, adverse move from entry)` (price units); `mfe_price`/`mae_price` = the extreme price, `mfe_time`/`mae_time` = time of the first sample reaching it (if the move is 0, the price is the entry and the time is `open_time`).
- `risk = |entry - initial_sl|`; `mfe_r = mfe_distance / risk`, `mae_r = mae_distance / risk`, rounded HALF_UP to 4 dp; None when there is no SL or risk is 0. MAE R may exceed 1 (gap / slippage through SL). Points = distance / symbol `point` (None when the point is unknown), 1 dp.
- No sample in range -> None ("unavailable").

### Price series (service)
- MT5 read-only: `copy_ticks_range(symbol, from, to, COPY_TICKS_ALL)` and `copy_rates_range(symbol, TIMEFRAME_M1, from, to)` (server epochs, like `history_deals_get`; times converted with the sync's broker-time conversion).
- Trade shorter than 2 h: ticks for the whole range. Longer: ticks for the entry minute (open_time .. next full minute) and the exit minute (last full minute .. close), M1 bars for the full minutes in between. Bar bid high/low = bar high/low; bar ask = bid + bar `spread` x point.

### Storage (migration; `trades`)
`mfe_price`, `mae_price` (PRICE), `mfe_time`, `mae_time` (timestamptz), `mfe_points`, `mae_points` (NUMERIC(14,1)), `mfe_r`, `mae_r` (RATIO), `excursion_status` (`final` | `running` | `unavailable`, CHECK), `excursion_source` (`ticks` | `m1_ticks`), `excursion_at` (timestamptz). MT5 raw data and the trade's other columns are never changed by it.

### When it runs
- In each account sync, inside the same MT5 connection (targets are read from the DB before it connects, so a trade is measured on the sync after the one that saw it close), stored after the sync committed (one savepoint per trade), with a 20 s budget per account: closed trades of the last 7 days without a final value and open trades (status `running`, «поточні»), each at most every 10 min (`excursion_at` = last attempt), least recently tried first, up to 5 + 5 per sync. A failure is logged and never fails the sync; an MT5 timeout ends the step. No or incomplete history (entry/exit-minute ticks missing) -> retried; `unavailable` only for a trade closed more than 24 h ago; never for an open trade. Setting the initial SL recomputes MFE/MAE R from the stored prices.
- Backfill: `python -m app.tools.backfill_excursions [--apply] [--account ID] [--retry-unavailable]` (dry run by default: computes and prints per trade and totals, writes nothing). Connects to MT5 read-only like `trade_check`; refuses while the worker may be running (a sync younger than the idle interval + 2 min); when an account's own terminal does not connect (e.g. a passed challenge whose terminal folder was removed), the price history is read from another configured terminal of the same broker (same MT5 server first, then any terminal of the same firm; active accounts first; archived never), each terminal opened only with its own configured account (investor login, as the worker does). Every result line names the terminal account and server it came from; output also goes to `logs/backfill_excursions.log`. No usable terminal: the account's trades are counted as errors and skipped (M8-16 fix 2026-11-19).

### API / UI
- `TradeRow` / `TradeDetail` add `mfe_r`, `mae_r`, `excursion_status`; `TradeDetail` adds `mfe_price`, `mae_price`, `mfe_points`, `mae_points`, `mfe_time`, `mae_time`, `excursion_source`, `excursion_at`. Journal: optional columns «MAE, R» / «MFE, R» (column chooser); trade details: both values with points and Brussels times, «поточні» for an open trade.
- Digest snapshot (strategy trades, M8-01 exclusions apply): `excursions: {winners_avg_mfe_r, losers_avg_mfe_r, losers_reached_1r, losers_reached_1r_share, n_winners, n_losers}` over trades with a final `mfe_r` (win/loss as in the digest's breakeven rule).

## M8-13 - Choose the Claude model (PM 2026-11-18)

- `config/ai_models.yaml`: `models: [{id, label, approx_usd: {trade_extraction, bias_extraction, digest_summary}}]` (strict; approx USD of one call). A new model = a new entry (plus prices in ai_pricing.yaml for the logged cost).
- `GET /api/ai/models` -> `{models: [{id, label, approx_usd}], defaults: {trade_extraction, bias_extraction, digest_summary}}`. Default per call type = the owner's choice (`DATA_DIR/ai_models.json`), else `.env` (ANTHROPIC_MODEL_EXTRACTION for trade and bias extraction, ANTHROPIC_MODEL_SUMMARY for the summary): nothing changes until the owner chooses.
- `PUT /api/ai/models/defaults {trade_extraction?, bias_extraction?, digest_summary?}` -> same shape; an id not in the list -> 422 `validation_error` (`details.fields.model`).
- One-off model: `POST /api/trades/{id}/extract` and `POST /api/bias/notes/extract` accept `model` in the body; `POST /api/digests/{id}/ai-summary` accepts an optional body `{model}`. Unknown id -> 422, no call (order everywhere: 404 -> 422 -> 503 ai_not_configured). A one-off model gets no fallback to another model. Without `model` and with a missing or broken ai_models.yaml the request uses the `.env` model (logged); at start the config check reports the broken file like every other config file. The UI sends `model` only when the owner picked one in the selector.
- `logs/ai_usage.jsonl` records `requested_model` and the `model` the API actually used (format unchanged).
- A model the API does not know (HTTP 404) -> 502 `ai_error` kind `model_not_found` (no fallback); UI: «Сервіс ШІ не знає вибраної моделі…».
- UI: Settings → «Моделі ШІ» (three selects with the approximate cost); a small selector «Модель ШІ для цього виклику» next to «Заповнити з тексту» (Describe and bias) and «Підсумок від ШІ».

## M8-14 - Charts on «Головна» (PM 2026-11-18)

- `GET /api/dashboard/charts?from=YYYY-MM-DD&to=YYYY-MM-DD[&account_id=N]` (Brussels dates, inclusive, 2000-01-01..2100-12-31; non-archived accounts; unknown account -> 404; to < from or a date outside the window -> 422; all accounts with trades in more than one currency -> 409 `mixed_currency`, like the digest; the UI asks to pick one account) -> `{from, to, currency, account_size, trades, equity: [{time, cum_pnl, cum_pct}], daily: [{day, net_pnl, pct, trades}], rolling: [{time, n, win_rate, avg_r}], rolling_window: 20}`. Money 2 dp, percents and R 4 dp, as strings.
- Equity (from 0 at Brussels midnight of `from`) and P&L by day: every closed trade of the range, M8-01 excluded trades included (account money; the equity end equals the digest's «P&L рахунку разом з виключеними» for the same period). Rolling win rate / average R: the last 20 strategy trades at each trade (excluded trades out, the digest's breakeven rule), the window reaching back before `from`; points shown for the range only.
- `account_size` / percents: one account's size, or the sum of the sizes of the accounts with a trade in the range (the digest's combined rule); null when any counted account has no finite size > 0. The charts refresh every 30 s like the rest of Home; a failed refresh keeps the last charts with an error note.
- UI: «Головна» → «Графіки»: «Тиждень» (Monday..today), «Місяць» (1st..today), «3 місяці» / «Рік» (same day back + 1), «Усе», «Свої дати»; account selector (all / each); selection remembered per browser (localStorage, try/catch); defaults «Місяць», all accounts; empty range «Немає угод за цей період». Plain SVG like the digest charts (EquityChart reused).

## M8-04..M8-08 - Journal taxonomy batch (PM 2026-11-19; contract)

Branch `m8/journal-taxonomy`, tier L, one migration. Merge A: config engine + `violations.yaml` + rules engine + migration + dry-run tool. Merge B: Describe UI, AI extraction, Journal filters, digest breakdowns/combinations.

### Engine (config/journal_fields.yaml)
- `multi_enum` = the PM's multi_select (already in the engine). New: `multi_enum` with `storage: column` is a `VARCHAR(50)[]` trades column (NULL when empty, never `{}`); `required` = at least one value.
- `allow_other_text: true` = the PM's other_requires_text, now also for `multi_enum` (the text applies when `other` is in the list). «Інше» without text: `complete` is refused (422 `journal_incomplete`, key = the text_key) as today; a draft may keep it. The text key has its own `journal_field_requirements` row (review 2026-11-19): it blocks only trades closed at or after that `required_since` (no row = counts, as before), and `missing_new_fields` lists it when the parent is `other`, the text is empty and the row is newer than the close. The migration stamps the new text keys (incl. `entry_model_other`) with now().
- New `show_if: {field: <key>, includes: <option value>}`: the field is shown, required and AI-fillable only when the parent's value equals (enum) or contains (multi_enum) the option. On save a hidden field and its text_key are stored as NULL; the `PUT .../journal` response lists them in `cleared_hidden` (the UI warns before saving: «Буде очищено: <label>»). Validation: the parent is an earlier enum/multi_enum field without its own show_if, the option exists.
- New `legacy: true`: read-only old field (the PM's «старе значення»). Not writable (422 `not_writable`), never required, not AI-fillable, not analytics, not a filter. `TradeDetail.journal` still returns it; the UI shows «Старе значення: <label>» only when it is not empty.
- New required fields get `required_since` = when they became required (existing M3-07 rule), so trades closed before stay complete; «Неповні за новими полями» lists them.

### New fields (journal_fields.yaml, form order)
| key | type | options | text_key | rules |
|-----|------|---------|----------|-------|
| `h1_context` «Контекст H1» | enum | flow «Flow», reversal «Reversal», range «Range», other «Інше» | `h1_context_other` | required, analytics |
| `h4_context` «Контекст H4» | enum | same | `h4_context_other` | required, analytics |
| `poi_types` «POI» | multi_enum | fvg_h4 «FVG H4», fvg_h1 «FVG H1», fractal_h1 «Fractal H1», fractal_h4 «Fractal H4», other «Інше» | `poi_types_other` | required (>= 1), analytics |
| `fvg_types_h1` «Тип FVG H1» | multi_enum | fractal_updating «оновлює фрактал», post_manipulation «після маніпуляції», other «Інше» | `fvg_types_h1_other` | show_if poi_types includes fvg_h1; required when shown; analytics |
| `fvg_types_h4` «Тип FVG H4» | multi_enum | same | `fvg_types_h4_other` | show_if poi_types includes fvg_h4; required when shown; analytics |
| `entry_model` (single, unchanged) | enum | label «Інше» for `other` | new `entry_model_other` | allow_other_text |
| `setup_context` «Контекст (Flow H1 синхронний з H4)» | enum | unchanged | — | `legacy: true` |
| `fvg_kind` «Тип FVG (старе)» | enum | unchanged | — | `legacy: true` |

`poi_type` / `poi_type_other` leave the YAML (columns kept; always mapped exactly, so the migration empties them).

### Violations (config/violations.yaml, new)
- `violations: [{key, label, type: auto|manual, status: active|deprecated}]`; the options of the journal field `rule_violations` come from this file (no options for it in journal_fields.yaml). Adding a manual violation = one entry; the file is re-read on change (FileCache), a restart also works.
- Validation: keys snake_case <= 50, unique; every key the rules engine emits is an active `auto` entry and every `auto` entry is an engine key; at least one active entry. Deprecated: shown on old trades and in history stats, not selectable on a trade that does not have it.
- Engine keys: `max_risk_pct`, `daily_risk` «Порушення денного ризику», `weekly_risk` «Порушення тижневого ризику», `max_trades_per_week`, `max_reentries_per_idea`, `min_planned_rr`, `entry_session`, `qm_not_in_ny`, `no_breakeven`. Thresholds stay in rules.yaml (`daily_stop_loss_pct` -3, `daily_stop_profit_pct` +5, `weekly_*` -6 / +10). `daily_risk` details name the limit hit, e.g. `daily_stop_loss_pct: day P&L reached -3.10% (...) before entry <= limit -3.0%` (both limits -> both parts joined by `; `).
- Old keys `daily_stop_loss_pct`, `daily_stop_profit_pct`, `weekly_stop_loss_pct`, `weekly_stop_profit_pct`: `auto`, `deprecated` (labels kept).
- New manual: `entry_not_by_model` «Вхід не за моделлю входу», `entry_weak_poi` «Вхід від слабкої POI», `entry_against_system` «Вхід не за торговою системою (не дотримуючись контексту H1/H4)».
- Trade details show each violation's `details` (migrated rows: the original key first); stats group by `rule_key` only.

### Migration (one revision; pre-migration backup via `make migrate`)
- Adds the columns above (`*_other` TEXT, multi columns VARCHAR(50)[]).
- `setup_context = yes` -> h1 = h4 = `flow`, setup_context NULL. `no` / `partially` -> new fields empty, setup_context kept (legacy).
- `poi_type` X -> `poi_types = [X]`, `poi_type_other` -> `poi_types_other`; poi_type / poi_type_other NULL.
- `fvg_kind` in (fractal_updating, post_manipulation) with poi_type fvg_h1 / fvg_h4 -> `fvg_types_h1` / `fvg_types_h4 = [kind]`, fvg_kind NULL. Otherwise (`na`, or POI not FVG) fvg_kind kept (legacy).
- `rule_violations` rows with an old daily/weekly key -> `daily_risk` / `weekly_risk`, details `<old key>: <old details>`; two rows of one trade merge into one (details joined by `; `, source = user if either was user).
- Inserts `journal_field_requirements` rows for the new required keys with `required_since = now()` (ON CONFLICT DO NOTHING); deletes the rows of keys no longer required (setup_context, poi_type, fvg_kind).
- Downgrade restores the old columns where one value exists (poi_types[1]; h1 = h4 = flow -> yes; one FVG type -> fvg_kind; old violation keys from the details prefix), then drops the new columns. Extra multi values are lost on downgrade (documented).
- Dry run: `uv run --project backend python -m app.tools.taxonomy_dry_run` dumps the dev DB, restores it into a scratch `*_taxdry_test` DB, upgrades it there, prints counts per mapping (mapped / kept as legacy / violations remapped / merged), drops the scratch DB. The dev DB is not changed. Same output in `logs/taxonomy_dry_run.log`.

### Analytics, filters, AI (merge B)
- Digest breakdowns for every analytics field; a multi field counts a trade in each selected value; `poi_types` also by combination (sorted values joined « + »); new table H1 × H4 (count, P&L, R, win rate). Each breakdown has coverage «заповнено N/M» (M = strategy trades where the field applies; show_if fields: only trades whose parent includes the option).
- Journal filters for every new field (multi: any of the chosen values).
- AI extraction: schema/catalogue from the YAML: multi values as a list, other-text keys, show_if fields kept only when the parent value includes the option (guard drops them otherwise), legacy never. Prompt, glossary examples and fixtures (UA/RU/EN) updated. No live calls; up to 5 proposed at the end.

### Merge B exact shapes (orchestrator 2026-11-19)
- `GET /api/journal-fields`: each field may carry `show_if: {field, includes}` (or null) and `legacy: bool`; `rule_violations.options` come from violations.yaml (`deprecated` set for deprecated entries) plus `violation_types: {<key>: "auto" | "manual"}` on that field. `violation_types` is informational (the UI marks auto keys); the owner may still tick an auto key by hand, as before.
- `PUT /api/trades/{id}/journal` -> TradeDetail + `cleared_hidden: string[]` (field keys sent with a value and hidden on save). The UI never sends legacy keys or `poi_type`; before saving it shows «Буде очищено: <labels>» when a hidden field still has a value.
- `GET /api/trades` journal filter: repeatable `journal=<key>:<value>` (`<value>` = option value, or `null` = empty). Same key = any of; different keys = all. Allowed keys: non-legacy enum / multi_enum / bool fields (bool values `true` / `false`); unknown key, legacy key or unknown option -> 422 validation_error with `details.fields.journal`. Multi fields match when the array contains the value (`null` = NULL array). A show_if field's `null` matches only trades where the field is shown (its parent includes the option) and empty (review 2026-11-19). Combined with the other filters.
- Digest snapshot `breakdowns` (map, file order): each entry gets `kind` (`field` | `combination` | `matrix`; a snapshot without `kind` = `field`).
  - `field`: as today; a multi field puts a trade in each of its values (`null` group = empty); `coverage.total` = strategy trades where the field applies (show_if: the parent includes the option), `filled` = those with a value. Hidden-field trades are in no group.
  - `poi_types__combo` (`combination`): one group per distinct selection, key = values in YAML option order joined « + » (one value = the value itself); empty -> `null`.
  - `h1_context__x__h4_context` (`matrix`): groups with `key: [h1, h4]` (either part may be null), same numbers per group; `coverage.filled` = trades with both set. UI: table H1 rows × H4 columns, each cell «N угод · P&L · R · WR», empty cells «—».
- Trade details (Journal dialog, Describe): each violation shows its label and `details`; legacy fields show «Старе значення: <option label>» when not empty.

## M8-10b - «Головна» rebuild (PM 2026-11-20; contract)

Branch `m8/home-redesign`, tier M, no migration. Layout and behaviour: docs/design/home-mockup.html (top to bottom). Existing endpoints reused: `GET /api/dashboard/charts` (hero P&L curve per range/account, «P&L по днях», «Форма · 20 угод»), the «Потрібен опис» list (M8-15), `GET /api/bias/status`. New: `GET /api/home?account_id=N` (omit = all active accounts).

```
{
  now, timezone: "Europe/Brussels",
  session: {key: "london"|"premarket"|"ny"|"outside", entries_allowed: bool},          # rules.yaml sessions, Brussels now
  bias_today: {pre_london: [{symbol, direction}] | null, pre_ny_missing: bool},          # today's notes; null = no pre-London note
  limits: {account_id, account_name, currency,
           day: {pct, loss_pct, profit_pct}, week: {...}, month: {pct, loss_pct, profit_pct},
           trades_week, max_trades_week, to_daily_stop_pct,
           balance, equity, balance_fresh},                                             # one account (see below); last synced figures, MT5 or cTrader
  kpis: {
    today:    {pnl, pct, trades, series: [{time, cum_pnl}]},                            # closed trades today, from 0 at Brussels midnight
    win_rate: {value, n, window: 20, series: [{time, value}]},                         # strategy trades (M8-01 exclusions out)
    avg_r:    {value, n, window: 20, series: [{time, value}]},
    drawdown: {pct, limit_pct, series: [{time, pct}]}                                   # from the running peak, this Brussels month
  },
  open_positions: [{trade_id, symbol, direction, volume, account_id, account_name, open_time,
                    entry_price, initial_sl, tp, current_price, price_time, pnl, r_now, tp_r,
                    mae_r, mfe_r, risk_pct, described: bool}],
  open_totals: {pnl, risk_pct, price_time}
}
```
- Money 2 dp, percents and R 4 dp, prices plain decimals, as strings (rounding is display only, «overview» formatter). Win rate / R series: last 20 points, same rules as the M8-14 rolling chart (breakeven by |R|). Money side (today P&L, limits, drawdown, open P&L) includes excluded trades.
- Limits card: one account. `account_id` given -> that account; all accounts -> the active account with the lowest `to_daily_stop_pct` (closest to its daily stop); the card shows its name and lets the owner switch (same query param). Month limits: new optional rules.yaml section `account_limits: {max_drawdown_pct: -10.0, profit_target_pct: 10.0}` (FundedNext; display only, no violations); missing -> month bar without limits. `to_daily_stop_pct` = day pct − daily_stop_loss_pct (e.g. +2.1 − (−3.0) = 5.1). `trades_week` counts every trade opened this Brussels week (excluded ones too: the limit is real).
- Drawdown series: running closed P&L of the month from 0; drawdown = (running − peak so far) / account size × 100 (≤ 0). `limit_pct` = account_limits.max_drawdown_pct.
- Open positions live values: the worker writes `DATA_DIR/open_positions.json` after every account sync (per position id: price_current, profit + swap, time; read-only MT5 positions_get). `current_price`, `pnl`, `r_now` are null when there is no snapshot or it is older than 5 minutes (UI: «ціна недоступна» / «дані застаріли HH:MM»). `r_now` = signed price move / initial SL distance; `tp_r` = TP distance / SL distance (null without SL or TP). `mae_r` / `mfe_r` = the running M8-16 values. `described` = a description was saved while open (M8-02).
- Errors: unknown account 404; broken rules.yaml -> config_error like the dashboard; a broken or missing snapshot never fails the endpoint (live fields null, logged once).
- UI (exact mockup order): header (Brussels date/time, chips «<сесія> · вхід дозволено / заборонено», «Лондон: EURUSD ↑ GER40 ↑», «+ Біас NY» when pre_ny_missing, «Калькулятор»); hero P&L (span 2, range selector «Тиждень/Місяць/3 міс/Рік/Усе/Дати», big total + %, value labels: all points ≤ 8 else every 3rd + min + last, min in loss colour below the line, last value pill, axis and dates) + «Ліміти» (day/week/month bars: hatched loss zone, gradient fill from zero, zero tick; «Угод 7 / 10», «До стопу дня»); «Відкриті позиції» (live dot, total P&L pill, risk pill, cards with price ladder SL→entry→TP, MAE–MFE band, current price dot and tag, −1R / 0 / TP R, ↓ MAE / ↑ MFE chips, description pill, «Описати»); 4 KPI toggle cards (Сьогодні, Win rate, Сер. R, Просідання) with sparklines that switch the hero chart, selected card ring ≥ 3:1 and «на графіку», click again or «← Крива P&L» returns; «Потрібен опис» tiles (up to 5 + «+N у журналі»); «P&L по днях» bars with value labels and «Форма · 20 угод» with end labels. All numbers through the «overview» formatter.
- Pinned in the backend (2026-11-20): `account_id` may name any non-archived account (archived / unknown -> 404); omitted = active accounts. `session.key` is `outside` (entries not allowed) on days outside rules.yaml `sync.trading_days`. `pre_ny_missing` is true only Mon-Fri. `limits` is null when there is no account; `day/week/month.pct` is closed P&L only (open P&L not counted), null when the account has no size > 0; `loss_pct`/`profit_pct` null when the rule is disabled or `account_limits` is missing; `max_trades_week` null when the rule is disabled; `to_daily_stop_pct` null when the day pct or the daily stop is unknown (such accounts are picked last for «all accounts», ties -> lowest id).
- KPI percents: one account -> its size; all accounts -> the combined size of the accounts with a trade in the period (today / this month), every selected account when none traded. `win_rate`/`avg_r`: `value` and `n` = the last rolling point (n = trades in its window); no strategy trades -> value null, n 0, series []; the `avg_r` series skips points without any R. `drawdown`: series starts with 0 at Brussels midnight of the 1st, then one point per closed trade; no size -> pct null, series [].
- Open positions: ordered by open time; `price_time` = the snapshot time of that position, kept even when stale (for «дані застаріли HH:MM»; only `current_price`, `pnl`, `r_now` go null) and null when it is not in the snapshot. `r_now`/`tp_r` use `initial_sl`; null when the SL is missing or not on the losing side of entry; `tp_r` is signed. Prices are the stored precision (e.g. `2650.00000000`, like `/api/dashboard`), the snapshot price as MT5 gave it. `open_totals`: `pnl` / `risk_pct` null when any position lacks the value (no partial sums), `price_time` = the oldest position time (null when any is missing); no positions -> `0.00` / `0.0000` / null.
- Selected accounts with trades this month or open positions in more than one currency -> 409 `mixed_currency` (as the charts). Snapshot file: `{account_id: {position_id: {price_current, profit, time}}}`, `profit` = MT5 profit + swap, `time` = the sync start (UTC); an account's entry is replaced on each successful sync (closed positions drop out), a failed sync leaves it to go stale.

### M8-10b fixes (2026-11-20)

- **A. Open positions**: `open_positions` / `open_totals` always list the open trades of every active account (plus the selected one), whatever `account_id` is; closed-trade money (KPIs, limits) still follows the selection. The 409 `mixed_currency` checks only the closed trades of the selection; open positions in more than one currency give `open_totals.pnl = null` (no 409).
- **B. One period P&L / % definition** (`app.domain.period_base`, used by `/api/home`, `/api/dashboard/charts` and digests): money = net P&L of the trades closed in the period (Brussels close date); account views include M8-01 excluded trades, strategy views (digest metrics) exclude them. % base: one account -> its `reference_balance`; all accounts -> sum of `reference_balance` of the non-archived accounts with >= 1 closed trade in the period, excluded trades included (none -> null; Home today KPI and drawdown fall back to every selected account); any non-finite / <= 0 size -> null. Digest combined and norm percents now count accounts whose only period trades are excluded. Digest snapshot `excluded` gains `account_net_pnl_pct` (4 dp string, null without a base) = `account_net_pnl` / the same base x 100, equal to the Home chart `cum_pct` of the month. Older snapshots lack the key (optional); stored digests change only on «Оновити».
- **C. Limits with floating P&L**: `limits` gains `floating_pnl` (money string or null) and `floating_included` (bool). Each bar `pct` = (closed net P&L of the period + floating) / reference_balance x 100, floating = `accounts.equity - accounts.balance` when `balance_synced_at` is not older than 5 min (the open-positions snapshot limit). Stale / unknown sync: with an open trade on the account -> `floating_pnl` null, `floating_included` false, closed P&L only; without one -> `"0.00"`, true. `to_daily_stop_pct` uses the new day pct. The rules engine, «СТОП» banner and violations stay on closed trades.
- **D. `bias_today.pre_ny_missing`**: true only on weekdays from the start of the rules.yaml `premarket` session (11:00 Brussels) until a pre-NY note exists; false before 11:00.

### M8-10b follow-ups (2026-11-20)

- **`kpis.max_loss`** (UI card «До макс. збитку», replaces «Просідання»; `kpis.drawdown` stays unchanged, the UI stops using it): `{account_id, account_name, pct, limit_pct, equity, equity_source: "mt5"|"balance"|"trades", series: [{time, pct}]}` or null when rules.yaml `account_limits` is missing or no candidate account has a size > 0. FundedNext static max loss: floor = size x (1 + `account_limits.max_drawdown_pct` / 100), size = `reference_balance`; `pct` = (equity - floor) / size x 100 (size 10 000, equity 10 056.25 -> floor 9 000, `10.5625`; 0 = failed). `limit_pct` = `max_drawdown_pct` (`-10.0000`). Equity now: `accounts.equity` of a balance sync not older than 5 min (`mt5`); else `accounts.balance` when set (`balance`, floating unknown); else size + all closed net P&L + the cash open trades already booked (their net_pnl, null -> 0) (`trades`); excluded trades count (real money). Series (whole account history): start point at the first trade's open time (`now` without trades) at -limit_pct, one point per closed trade on size + cumulative closed P&L, final point at `now` with equity now; the last 60 points. One account -> that account; all accounts -> the active account with the lowest `pct` (ties -> lowest id). Money 2 dp, pct 4 dp strings.
- 2026-11-20 follow-up: `kpis.max_loss.limit_pct` and `limits.month.loss_pct` / `profit_pct` are per account: the account's Settings firm rules (`max_drawdown_pct` -> negative limit, `profit_target_pct`) when set, else rules.yaml `account_limits`. `max_loss` is null when no account has both a size and a limit.

## Starting balance suggestion (2026-11-20)

- **Field**: every account response (`GET /api/accounts` items, `GET` / `POST` / `PATCH /api/accounts/{id}`) gains `starting_balance_suggestion: {amount: "10000.00", time: "2026-11-10T12:53:00Z"} | null` (money 2 dp string, UTC). Non-null only when the suggestions file has an amount for the account and it differs from the stored `starting_balance`.
- **Confirm**: the existing `PATCH /api/accounts/{id}` with `{"starting_balance": "<amount>"}` (same validation as create: positive, max 2 decimals, decimal string). Afterwards the amounts are equal, so the field is null. `reference_balance` is not changed.
- **Source**: `DATA_DIR/starting_balance_suggestions.json`, written by the worker (atomic replace): `{"<account_id>": {"amount": "10000.00", "time": "...Z", "ticket": 194830322, "checked_at": "...Z"}}`, or `{"amount": null, "checked_at": "...Z"}` when the history has no deposit. An account without an entry (new account, first sync) reads its full MT5 deal history once (read-only `history_deals_get`, inside the normal sync connection); the first deposit = the earliest non-trade deal (MT5 type not 0 buy / 1 sell, e.g. 2 balance or 4) with profit > 0, amount = profit + commission + swap + fee. A failed history read or file write never fails the sync (warning / error in the log; a failed read is retried on the next sync). A missing or broken file means no suggestion (logged once).

## Editable journal option lists (owner request 2026-11-22)

- Managed fields: `emotion_before`, `emotion_after` (`MANAGED_FIELDS` in `app/services/journal_options.py`); any other field -> 404.
- `GET /api/journal-options/{field}` -> `{field, options: [{value, label, hidden, synonyms, used_count}]}`.
- `POST /api/journal-options/{field}` `{label, synonyms?}` -> 201 option (`value` = generated stable `opt_<hex>`); same label -> 409 `duplicate_label`.
- `PATCH /api/journal-options/{field}/{value}` `{label?, hidden?, synonyms?}`; `value` never changes; hiding the last visible option -> 409 `last_visible_option`.
- `PUT /api/journal-options/{field}/order` `{values}`: every current value exactly once, else 422.
- `DELETE /api/journal-options/{field}/{value}` -> 204; used by a trade -> 409 `option_in_use`.
- `GET /api/journal-fields` returns the current lists; `hidden` is `deprecated`; every option carries `synonyms`. With the DB down it returns the YAML defaults (logged).

## cTrader integration, phase a (owner 2026-11-23)

Read-only: OAuth, account list, saved accounts, balance and equity on Home. No deals, trades, positions in the journal, symbol specs or MAE/MFE yet. Every outgoing message passes the allowlist in `app/ctrader/guard.py`.

`Account` gains `platform`: `mt5 | ctrader` (read-only: POST and PATCH of `/api/accounts` refuse it). For a cTrader account `login` = traderLogin, `server` = broker title (or `cTrader`), `terminal_path` = null, `password_env_key` = `""`, `password_configured` = `true` (no password exists, nothing is missing). PATCH refuses a changed `login`, `server` or `terminal_path` with `422 validation_error` (`details.fields`); the same values may be resent.

- `GET /api/ctrader/status` -> `{ "configured": true, "connected": true, "error_code": null }`. No network call. `error_code`: `not_configured`, `token_expired`, `token_invalid`, `token_store_failed`, or null.
- `POST /api/ctrader/connect` -> `{ "authorize_url": "https://id.ctrader.com/..." }`. Scope is always `accounts`; the `state` is single use and lives 10 minutes.
- `GET /api/ctrader/callback?code&state` (or `error`) -> `302` to `http://127.0.0.1:5173/settings?ctrader=connected` or `?ctrader_error=<code>`, with `Cache-Control: no-store`. Codes: `not_configured`, `state_invalid`, `access_denied`, `bad_response`, `token_invalid`, `token_store_failed`, `timeout`, `connection_failed`, `client_auth_failed`, `not_authorized`, `rate_limited`, `trade_scope_refused`, `internal_error`. The redirect never holds a token or the code. It is the only endpoint open to a cross-site browser request, and only as a top-level GET navigation (`app/local_boundary.py`); the state check protects it.
- `GET /api/ctrader/accounts` -> `{ "items": [ { "ctid_trader_account_id": 7001, "is_live": false, "trader_login": 5100200, "broker": "Broker", "already_added": false } ] }`. `trader_login` may be null (optional in cTrader's model); such an account cannot be added.
- `POST /api/ctrader/accounts` body: `ctid_trader_account_id` + `name`, `firm`, `program`, `phase`, `starting_balance`, `currency`; optional `status`, `reference_balance`, `daily_loss_pct`, `max_drawdown_pct`, `profit_target_pct` -> `201 Account`. Same validation as `AccountInput`; unknown keys (`login`, `server`, `platform`, `terminal_path`) are 422. `422 ctrader_account_not_granted` (id not in the token's list), `422 ctrader_account_incomplete` (no login), `409 conflict` (`details.field`: `name` or `ctid_trader_account_id`). Two cTrader accounts may share a login and broker title; MT5 accounts stay unique by login + server.
- `DELETE /api/ctrader/connection` -> `204`, idempotent. Forgets the tokens; accounts stay and then show `token_invalid`.

Errors use the standard envelope with code `ctrader_<code>`: `503 ctrader_not_configured`, `409 ctrader_token_invalid` / `ctrader_token_expired`, `403 ctrader_not_authorized` / `ctrader_trade_scope_refused`, `429 ctrader_rate_limited`, `504 ctrader_timeout`, `502` for the others.

Worker job `ctrader_balance` (independent of the MT5 job and lock, same cadence rule as MT5: 60 s in trading hours, the idle interval otherwise; at most 45 s of work per run): reads 2121, 2187, 2121 and accepts the P&L only if both balances are equal (one retry, then `equity_unavailable`). Equity = balance + the sum of `netUnrealizedPnL`, each scaled by its own `moneyDigits` (Decimal). The docs do not state this formula, and net P&L excludes the potential closing commission. One `sync_log` row per account and attempt; `GET /api/sync/status` applies the same stale rule as MT5. `token_invalid` means reconnect required: after a refused refresh the token endpoint is not asked again for 1 hour unless the owner reconnects. New `error_code` values: `not_configured`, `token_expired`, `token_invalid`, `token_store_failed`, `not_authorized`, `client_auth_failed`, `connection_failed`, `rate_limited` (state `warning`), `bad_response`, `account_disconnected`, `equity_unavailable`, `internal_error`; `timeout` is shared with MT5. On `equity_unavailable` the stored balance, equity and `balance_synced_at` stay unchanged, because Home derives the floating P&L from their difference; an account with no stored equity gets the balance alone.

`POST /api/calculator/margin-requests` answers `409 margin_unsupported_platform` for a cTrader account (live margin is MT5 only).

## cTrader integration, phase b (owner 2026-11-24): trades, open positions, reconcile

No endpoint changes. The `ctrader_balance` job now also reads, in the same connection and still read-only, ReconcileReq 2124 (open positions), DealListReq 2133 (deal history, one-week windows, `hasMore` answered by halving the window, historical limit 5 req/s), SymbolsListReq 2114 (names, archived included) and SymbolByIdReq 2116 (digits, `lotSize`). Closed and open positions become `trades` / `trade_exit_deals` rows through the same writer as MT5 (`app/services/trade_writer.py`), so the trades table, Home, limits, digests, rules, exclusions, bias alignment and the «Потрібен опис» inbox treat them as MT5 trades.

- `trades.volume` is in lots: cTrader volume / the symbol's `lotSize` (exact; a position whose lot size is unknown or does not divide its volume is skipped and reported as `positions_skipped`). `symbol` is canonical via `config/symbols.yaml` (e.g. `DE40` -> `GER40`), `broker_symbol` the cTrader name.
- Money of a closed volume comes from `closePositionDetail` (`grossProfit`, `swap`, `commission`, `pnlConversionFee` folded into commission); entry deals carry no money. `initial_sl` is the first SL seen on the open position (source `position`); a trade first seen closed is `needs_sl`. No symbol specs, FX checks or MAE/MFE for cTrader yet (phase c).
- `GET /api/home` `open_positions[]` for a cTrader account: `current_price` and `r_now` are always null (no quote is read), `pnl` = the position's `netUnrealizedPnL` (null when equity was not read), `close_unconfirmed` as for MT5. `open_positions.json` entries may hold `price_current: null` / `profit: null`.
- `sync_log` rows of cTrader accounts now fill `deals_fetched`, `trades_created`, `trades_updated`, `open_positions`. `ok` is true only when balance, equity and trades all worked; `positions_skipped` keeps `ok` true (warning). New `error_code` `history_incomplete`: a DB-open trade or a reported position opened inside the read range has no entry deal in the answer; nothing about trades is written (the balance is), the window does not move, retried next cycle. A history read failure (`bad_response`, `rate_limited`, `timeout`, ...) also keeps the balance.
- History window per account: from the last `ok` run that read at least one deal and skipped no position, minus `overlap_days` (first run, or none such: `initial_history_days`, never further back), extended back to the open time of every DB-open trade and reported position, 1 minute earlier, up to now (never in the future), at most 370 days. Known limit: an old DB-open trade makes every cycle re-read from its open time (up to ~53 one-week requests, ~11 s per account at 5 req/s, inside the 45 s budget).
- Reconcile: a new position with an entry deal that cTrader does not report open and the deals do not close is not written; the row is `ok` with `positions_skipped` and the position in `error_message` ("not reported open by cTrader and not closed in the history"), retried next cycle. Closed = closed volume >= entered volume; a shortfall keeps the trade open (`close_unconfirmed`), an excess is skipped. A DB-open trade's stored `last_sl` / `tp` survive its close. `swap` / `commission` missing from `closePositionDetail` count as 0; `grossProfit` is required.
- When equity is not read and positions were skipped, the row shows `equity_unavailable` (ok false) with both messages joined by `; `.
- `balance_at_open` ignores cTrader cash flow (deposits / withdrawals are not read), so after a deposit or withdrawal it is off by that amount (information only).

## cTrader integration, phase c (owner 2026-11-24): specs, calculator, MAE/MFE, limits

Read-only as before. The allowlist grows only by **2112** (asset list), **2137** (trendbars) and
**2145** (tick data); the guard test pins it. Recorded/sanitized fixtures only, no live calls in tests.
All field names below are assumptions from the Open API docs, to confirm on the first live run.

### c1. Symbol specs -> `symbol_specs` (same table and columns as MT5)
- Symbols: the broker names of `config/symbols.yaml` (same resolution as MT5, incl. aliases/firms)
  plus every symbol of a DB-open or recent trade, plus the conversion pairs of c2.
- From 2114 light symbol (`symbolId`, `symbolName`, `baseAssetId`, `quoteAssetId`), 2116 full symbol
  (`digits`, `pipPosition`, `lotSize`, `minVolume`, `stepVolume`, `maxVolume`; volumes and lotSize are
  in cents of a unit) and 2112 assets (`assetId`, `name`).
- Mapping: `contract_size = lotSize / 100`; `tick_size = point = 10^-digits`;
  `volume_min/step/max = minVolume/stepVolume/maxVolume / lotSize` (lots, exact Decimal);
  `currency_profit` = quote asset name; `currency_margin` = base asset name;
  `tick_value = tick_value_loss = contract_size * tick_size` (in the profit currency; used as is only
  when profit currency == account currency); `mt5_loss_per_tick` = NULL (no order_calc_profit on cTrader);
  `synced_at` = read time. A symbol with a missing/non-positive field is skipped with a WARNING, never written half.
- Refresh: on the first cycle and then at most once per hour per account (specs rarely change).

### c2. Conversion rate -> `fx_rates` (same rule as MT5, M5-09)
- Cross-currency spec (profit != account currency): `pick_conversion_pair` among the cTrader symbol names
  (direct `<P><A>` -> ask, inverse `<A><P>` -> 1 / bid). Quote = the last BID and the last ASK tick (2145,
  `type` 1 = BID, 2 = ASK) in the last 60 min; none (weekend) -> the last 3 days; none -> WARNING, the old row stays.
- Loss per tick per lot = `tick_size * contract_size * rate` (`loss_per_tick_from_rate`), the MT5 rule.
- The same value feeds the trade risk of c3 and the calculator (`calculator_fx.conversion_for`, source
  `rate` because `mt5_loss_per_tick` is NULL).

### c3. Trades
- `write_ctrader_trades` passes the cTrader specs and FX loss per tick to `TradeBatch`, so open and breakeven
  trades get their risk from the initial SL like MT5 trades.

### c4. Calculator
- Works unchanged from `symbol_specs`/`fx_rates`. Live margin stays 409 `margin_unsupported_platform` for cTrader;
  the UI shows a cTrader-specific Ukrainian line instead of the MT5 margin text.

### c5. MAE / MFE (same definitions as M8-16)
- Same targets, retry and final/running/unavailable rules (`excursion_targets`, `evaluate`, `store_excursions`).
- Ticks (2145, BID and ASK, merged by timestamp) for trades < 2 h and for the entry and exit minutes;
  M1 trendbars (2137, `period` 1, `low` + `deltaHigh`, prices in 1/100000, `utcTimestampInMinutes`) in between.
- Trendbars are BID only: a long uses them as is; a short adds a spread equal to the median ASK-BID of the
  entry and exit tick samples (`bar(..., spread_price)`); no tick samples -> the middle stays bid with spread 0
  and the series is incomplete (retry, then unavailable as for MT5).
- Inside the 45 s cycle budget, at most `BUDGET_S` for MAE/MFE per account; a rate-limit wait ends the step.
- Built (c5): `app.ctrader.excursions` (`BUDGET_S` = 8 s, read at call time); the reader step runs after the market step and
  returns `BalanceRead.excursions` (`Fetched`); the job picks targets with `excursion_targets` before the read and stores
  them after the trades with `store_excursions` in a savepoint. `hasMore` (2145/2137) halves the range, max 16 requests
  per window, else the series is incomplete. A cut-off, timeout, dropped connection or rate-limit error ends the step.

### c6. Limits
- Home «Ліміти», daily/weekly stops and rules use the cTrader trades and account size exactly like MT5
  (no platform branch); tests prove it for a cTrader account.

## Firm rules from config: KeyFunding (PM 2026-11-26; tier L, no migration)

The cTrader account is a **KeyFunding** account (not FundedNext). Firm rules live in a new
config file, not in code. FundedNext accounts keep their current rules unchanged (no
`firms.yaml` entry: per-account Settings values, then rules.yaml `account_limits`).

### `config/firms.yaml`
```yaml
firms:
  KeyFunding:
    daily_loss_pct: 4.0          # > 0, percent of the account size (reference_balance)
    max_loss_pct: 8.0            # > 0
    max_loss_type: static        # only `static`: floor = size x (1 - max_loss_pct/100), never moves
    profit_target_pct: { phase_1: 8.0, phase_2: 4.0 }   # per accounts.phase; funded: none
    daily_basis: balance         # start-of-day BALANCE (only value supported now)
    daily_reset: "00:00"         # HH:MM, wall time in reset_timezone
    reset_timezone: server       # `server` = broker server time (accounts.server_offset_hours
                                 # when detected, else UTC: cTrader sends UTC), or an IANA name
    to_verify: [daily_basis, daily_reset]   # shown in Settings and reports as «перевірити»
```
- Loader `app/config_files/firms.py`, strict pydantic like symbols.yaml (no extra keys, percents
  in (0, 100), firm names unique case-insensitively, `to_verify` items from the known field
  names), cached and reloaded on change. Missing file = no firms. A broken file is a visible
  ConfigError (API 500 with the config message, worker log ERROR), never silently ignored.
- Firm match: `accounts.firm` vs the key, case-insensitive, spaces/`-`/`_` ignored
  ("Key Funding" = "KeyFunding").

### Effective firm rules of one account (`app/domain/firm_rules.py`, pure)
Per field: the account's own Settings value when set (> 0), else the firm config value.
- max loss % and profit target %: account value -> firm config (target by phase) -> (no firm entry
  only) the existing rules.yaml `account_limits` fallback (unchanged behaviour of `firm_limits`).
- daily loss %: account `daily_loss_pct` -> firm config. The firm daily floor exists ONLY for
  accounts with a firm entry (it needs basis + reset); FundedNext gets no new daily floor.
- `source` per account: `firm` (a firm entry matched), `account` (no entry, own values),
  `fallback` (rules.yaml), `none`.

### Firm day (pure function)
- `reset_at` = latest moment <= now at which the reset wall time occurs in the reset zone (UTC aware).
- Start-of-day balance: fresh balance (synced <= snapshot STALE_AFTER) minus net P&L of trades
  closed at/after `reset_at` minus cash booked by open trades opened at/after `reset_at`;
  without a fresh balance: size + closed net P&L before `reset_at` + cash booked by open trades
  opened before `reset_at`.
- Day P&L = closed since reset + booked since reset + floating (equity - balance of a fresh sync;
  0 when nothing is open; unknown -> pct/room None).
- Limit amount = size x daily_loss_pct/100 (of the account SIZE, to verify). Floor = start balance - amount.
- `pnl_pct` = day P&L / size x 100; `room_pct` = daily_loss_pct + pnl_pct (0 or less = breached).

### API additions (all optional/nullable, existing fields unchanged)
- `AccountOut.firm_rules: FirmRulesOut | null` (null when source `none`):
  `{firm, source, daily_loss_pct, max_loss_pct, max_loss_type, profit_target_pct, daily_basis,
  daily_reset, reset_timezone, to_verify: string[]}` (Decimals as strings, effective values).
- `AccountLimitsOut.firm_day: FirmDayOut | null` (only accounts with a firm entry):
  `{reset_at, start_balance, floor, loss_pct (negative, e.g. "-4.00"), pnl_pct | null,
  room_pct | null, breached: bool, to_verify: string[]}`.
- «До макс. збитку» (`max_loss`) and the month bar use the effective max loss / target above.
- `GET /api/dashboard` `stop.firm_day: bool` (some account breached its firm daily floor) and
  `stop.firm_max_loss: bool` (some account at/below its static floor).

### Rule check
- New auto violation `firm_daily_loss` (config/violations.yaml, type auto): an entry opened after
  the account's realized firm-day P&L (trades closed before the entry, since that entry's firm
  day reset) reached <= -daily_loss_pct of size. Sticky within the firm day, like daily_risk.
  Only accounts with a firm entry. Personal rules.yaml stops (-3 % etc.) stay for every account.
- No `firm_max_loss` violation (an account at the floor has failed; KPI + banner only).

### UI (Ukrainian, uk.ts)
- Settings account form/table: under «Правила фірми» a note with the effective firm rules and
  «перевірити: …» for each `to_verify` item.
- Home «Ліміти»: a row «Денний ліміт фірми» (bar to loss_pct, room, reset time) when `firm_day`.
- Dashboard stop banner: lines for firm daily limit and firm max loss.

### Review fixes (2026-11-26)
- `firms.yaml` is checked at the start of every MT5 / cTrader sync cycle and by the risk-base
  recompute / symbol-map re-apply: a broken file skips the cycle ("sync skipped: <config message>")
  before anything is written, like a broken rules.yaml.
- Accounts API: a broken `firms.yaml` gives `firm_rules: null` on GET (one ERROR log per request,
  one WARNING for a broken rules.yaml); POST / PATCH refuse with 500 `config_error` before writing.
  PATCH of `firm` or `daily_loss_pct` (as of `reference_balance`) recomputes the account's rule violations.
- `daily_loss_pct` must not exceed `max_loss_pct`; write `daily_reset` in quotes (an unquoted `10:30`
  is read as a number by YAML).
- `firm_day.breached` is also true when the floating P&L is unknown but the realized loss of the firm
  day alone has reached the limit (`room_pct` stays null).
- Cash booked by a still-open trade is bucketed by when it was booked: each exit deal (profit +
  commission + swap) at its own time, the rest (entry commission) at the trade's open time.
- A server offset outside +-23 h is treated as UTC (WARNING), never a 500.
- Reset zone `server` uses the CURRENT detected offset: the firm days of an MT5 account in the past can
  shift by 1 h across a DST change, so for MT5 firms prefer an IANA `reset_timezone`. A firms.yaml
  edit reaches stored violations at the next worker start (`recompute_all`).

### PM answers 2026-11-26 (branch `ctrader/firm-alerts`)
- Firm limits and personal stops are shown together. Personal stops keep the StopBanner («СТОП на сьогодні»). A
  firm limit (`stop.firm_day` / `stop.firm_max_loss`) gets its own critical red banner (`FirmLimitBanner`) above it.
- `AccountLimitsOut.firm_alert: {kind: "firm_day" | "max_loss", room_pct: Pct | null} | null`. It is set when the firm
  daily room or the static max-loss room is <= 1 % of the size (`FIRM_ALERT_ROOM_PCT`), or when the firm day is
  breached (room null = breached on realized loss, floating unknown). When both are near, it names the closer one.
  The max-loss room counts for every account with an effective max loss (FundedNext Settings values too). The firm day
  counts only for firms.yaml accounts.
- «Усі рахунки»: an alerted account is picked first (smallest room, unknown first), else the closest to the personal
  daily stop as before. The card turns red and names the firm limit.
- KeyFunding (Borys confirmed): daily limit = start-of-day balance − 4 % of the size. The day resets 00:00 server
  time EET (`reset_timezone: EET`, IANA EET/EEST). `to_verify: []`.

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
{ "id": 5, "trade_id": 10, "bias_entry_id": null,
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

Settings (`.env`): `WHISPER_MODEL` (default `small`), `WHISPER_COMPUTE_TYPE` (`int8`), `WHISPER_LANGUAGE` (`uk`; empty = auto-detect), `WHISPER_BEAM_SIZE` (1), `WHISPER_CPU_THREADS` (`auto` = physical core count, detected once; 0 = library default; or a number 1–256), `WHISPER_VAD_FILTER` (`true`: bundled Silero VAD skips silence), `WHISPER_CONDITION_ON_PREVIOUS_TEXT` (`false`), `WHISPER_TEMPERATURES` (`0.0,0.4`: comma-separated, ascending, each 0–1; `0` = no temperature fallback), `DATA_DIR` (default `data` in the repo root). Glossary for `initial_prompt` in `config/transcription.yaml` (`glossary: [...]`), reloaded on change like the other config files.

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
- Matching is case-insensitive and on word boundaries (no letter/digit right before/after); longest `from` first; one pass. `to` is inserted as written.
- Applied by the worker to the transcript when a note becomes `done`; `AudioNote.transcript` is the normalized text (the UI shows it in the editable text box as before).
- Validation: `replacements` list (≤ 200), each `to` non-empty, `from` non-empty list of unique non-empty strings; the same `from` (case-insensitive) under two `to` is an error; mojibake is refused like every config file. Broken file → transcript stored unnormalized + ERROR in worker.log (the note is still `done`). Checked at API and worker start.

### AI key status (M3, PM 2026-11-05)

- `GET /api/health` gets `"ai": { "state": "ok" | "invalid_key" | "not_configured" | "unreachable" | "checking", "checked_at": "<UTC ISO>" | null }`. `status` stays based on the DB only.
- `GET /api/ai/usage` gets the same `"key_state"` value (Settings).
- `POST /api/ai/check` → re-checks now (blocking, ≤ 10 s) and returns the `ai` object.
- States: `not_configured` = no key in env/.env; `checking` = check running (start); `ok` = `models.retrieve` succeeded; `invalid_key` = 401/403 (also set when an extraction gets an auth error); `unreachable` = timeout / connection / 5xx (re-checked automatically every 5 min while unreachable).
- UI: status bar shows an AI chip only when the state is not `ok`/`checking`: "AI: ключ недійсний" / "AI: ключ не задано" / "AI: немає зв'язку"; Settings → AI shows the state with a "Перевірити ключ" button (POST /api/ai/check). A new key still needs an app restart (settings are cached).

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

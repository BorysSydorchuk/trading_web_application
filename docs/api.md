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
- `trades` (count), `wins` (net_pnl > 0), `losses` (< 0), `breakeven` (= 0).
- `net_pnl` (sum, account currency; all accounts USD today, a mixed-currency set → 409 `mixed_currency`), `net_pnl_pct` = net_pnl / sum of account sizes of the accounts with a trade in the period × 100 (one account: its size).
- `total_r` (sum), `win_rate` = wins / trades × 100 (breakeven is not a win), `avg_win_r` (mean R of wins), `avg_loss_r` (mean R of losses, negative), `expectancy_r` = total_r / n.
- `profit_factor` = sum of winning net_pnl / |sum of losing net_pnl|; null when there is no loss.
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
- `GET /api/digests/{id}` → full digest; `GET /api/digests/by-period?kind=&date=` → digest or 404.
- `PATCH /api/digests/{id} {what_worked?, what_to_fix?, focus_next?}` (text, max 10 000 chars, `""` → null).
- Next-period bias: the digest page embeds the existing bias note form (`POST/PUT /api/bias/notes`, kind weekly/monthly, date = next period start). The digest response has `next_bias_note_id` (null if none yet).
- `GET /api/digests/suggestion` → `{weekly: {period_start} | null, monthly: {period_start} | null}`: weekly from Friday 16:00 Brussels; monthly from 16:00 on the last trading day (last weekday Mon–Fri) of the month. A suggestion stays until that period's digest has a saved review (any of what_worked / what_to_fix / focus_next non-empty), also after the period ended, not just on that day (PM 2026-11-13). When several periods are unreviewed, the oldest unreviewed period of each kind is returned (DECISIONS 2026-11-13). Only periods from the first closed trade on are suggested. Shown on «Головна» and «Дайджести».
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

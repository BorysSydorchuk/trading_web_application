# Backlog

Ideas outside the current milestone. The PM decides when they enter a milestone.

| Date | Idea | Source | Notes |
|------|------|--------|-------|
| 2026-10-31 | Tie launcher child processes to a Windows Job Object (KILL_ON_JOB_CLOSE) so ending `dev.py` from Task Manager doesn't leave API/worker/Vite running | QA (M0) | Fits M7 hardening; Ctrl+C path already clean |
| 2026-10-31 | Frontend unit tests (Vitest) for `api/client.ts` and `lib/errors.ts` | code-reviewer (M0) | Add when frontend logic grows (M1/M2) |
| 2026-10-31 | Review `npm audit` moderate advisory (minimatch via eslint/typescript-eslint, dev-only) | frontend-dev (M0) | Re-check on next eslint upgrade |
| 2026-10-31 | README note: two checkouts running at once need different `POSTGRES_PORT` in `.env` | code-reviewer (M0) | One line in README |
| 2026-11-01 | Avoid cmd "Terminate batch job (Y/N)?" prompt after Ctrl+C in start.bat | PM (M0 review) | Moved out of M1 by PM |
| 2026-11-01 | Netting accounts: support `inout` position reversals in the trade builder (currently skipped with a visible reason) | code-reviewer (M1) | FundedNext accounts are hedging; only needed for a netting broker |
| 2026-11-04 | Show rule-violation specifics (e.g. by how much a limit was exceeded) in Ukrainian, built from structured `details` instead of the English text the rules engine stores | code-reviewer (M2-08) | M2 shows only the rule label |
| 2026-11-04 | Extraction: ignore a repeated identical multi_enum option instead of dropping the field; tests for unknown multi_enum option, bool "false", conflicting unknown key; log late usage of abandoned AI calls | code-reviewer (M2 latency fix) | Small, optional |
| 2026-11-04 | Client `isInProgramFiles` (frontend/src/features/accounts/form.ts) does not normalise `..` or trailing dots like the server (blocks `C:\Program Files\..\MT5\…`, allows `C:\Program Files.\…`); server stays authoritative | code-reviewer (M2-09) | Rare inputs, no safety impact |
| 2026-11-04 | Extraction prompt: for a number, quote only the words that state it (a sentence-long quote with a second number now drops the rating); re-run ai-eval after | code-reviewer (M3-02) | Small, needs a live eval |
| 2026-11-04 | Number guard: treat "з половиною / с половиной / and a half" after a number as joined (like a decimal), so a spoken 4.5 is not kept as 4 | code-reviewer (M3-02) | Rare |
| 2026-11-04 | Describe: after a save that stays on the page (unsent recording), reset the form baseline so leaving later doesn't warn; separate toast text for "still uploading" vs "failed"; optional confirm on "Видалити запис" | code-reviewer (M3-06) | Small UX polish |
| 2026-11-04 | Turning on `allow_other_text` later for a field whose old complete trades already store `other` puts `<field>_other` into their `missing_required` (M2 rule, not covered by required_since) | code-reviewer (M3-07) | Rare, only on a YAML change |
| 2026-11-04 | Describe: a field made required after the trade closed but already filled at load is treated as required by the client if the user clears it (blocks "complete" though the server accepts); a full fix needs the server to send the per-trade exempt fields | code-reviewer (M3-08) | Rare; client only knows `missing_new_fields` (empty fields) |

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
| 2026-11-04 | Extraction int guard: a spaced range "4 - 5" still passes as either number | code-reviewer (M2-07) | Rare; joined ranges "4-5" are already rejected |
| 2026-11-04 | Extraction: ignore a repeated identical multi_enum option instead of dropping the field; tests for unknown multi_enum option, bool "false", conflicting unknown key; log late usage of abandoned AI calls | code-reviewer (M2 latency fix) | Small, optional |
| 2026-11-04 | Client `isInProgramFiles` (frontend/src/features/accounts/form.ts) does not normalise `..` or trailing dots like the server (blocks `C:\Program Files\..\MT5\…`, allows `C:\Program Files.\…`); server stays authoritative | code-reviewer (M2-09) | Rare inputs, no safety impact |

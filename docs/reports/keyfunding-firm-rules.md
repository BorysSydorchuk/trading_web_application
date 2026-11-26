# KeyFunding firm rules (PM 2026-11-26)

Tier L, no migration. Branch `ctrader/keyfunding-rules` from main 262b8ab. Contract: `docs/api.md`,
"Firm rules from config: KeyFunding" (+ "Review fixes").

## What was built
- The cTrader account belongs to **KeyFunding**, not FundedNext. Firm rules are in the new `config/firms.yaml`, not in code.
  KeyFunding: daily loss 4 %, max loss 8 % static (floor = size × 0.92), profit target 8 % (phase 1) / 4 % (phase 2),
  start-of-day balance, reset 00:00 server time (cTrader: UTC).
- **To verify by Borys:** (1) the daily basis: 4 % of the account size below the start-of-day balance; (2) the reset
  time: 00:00 broker server time. Both are shown as «Перевірити» in Settings.
- Precedence per field: the account's own Settings value, then firms.yaml, then (firms without an entry only) the
  rules.yaml `account_limits` fallback. FundedNext has no entry and behaves as before.
- Home «Ліміти»: a new row «Денний ліміт фірми» (bar, «до ліміту» rounded down, «день фірми з HH:MM», red when it is
  breached). «До макс. збитку» and the month bar use the firm rules. The dashboard stop banner has firm lines.
- New auto violation `firm_daily_loss` («вхід після денного ліміту фірми»). It uses realized P&L, is sticky inside
  the firm day, and applies only to firms with an entry.
- The personal rules.yaml stops (−3 % day etc.) stay for every account. The firm limits are added next to them.
- A broken firms.yaml skips the MT5/cTrader sync and recompute cleanly before any write. Settings GET shows no firm note
  and logs one ERROR. POST/PATCH refuse before writing.

## Tests
- 258 new and touched backend tests, plus a wider related run of 2027 passed / 1 skipped. Coverage: firms.py and
  firm_rules.py 100 % (non-DB). Frontend: 17 new tests, plus 18 for the rounding fixes.
- Full gate: see the merge commit message.

## Reviews
python-reviewer and code-reviewer CHANGES REQUESTED (HIGH: firms.yaml read after writes; stale violations after a
firm/daily-loss edit), then fixed, then both APPROVE. The LOW items are in BACKLOG.

## Open questions for the PM
1. Firm limits are added next to the personal stops rather than replacing them. Is that right?
2. With «Усі рахунки», «Ліміти» picks the account closest to the personal stop, not to the firm floor.
3. The KeyFunding daily basis and reset time (to verify by Borys).

## Known limits
- `server` reset zone uses the currently detected MT5 offset, so past firm days of an MT5 firm can shift 1 h across a
  DST change. Use an IANA zone for MT5 firms. A firms.yaml edit reaches stored violations at the next worker start.
- KeyFunding symbol aliases: after the live cTrader symbol list (live check, task d).

## Update 2026-11-26 (PM answers, Borys checks)
- Borys confirmed the daily basis. The reset is 00:00 server time EET (`reset_timezone: EET`), so nothing is left to verify.
- Firm limits apply together with the personal stops and have their own critical banner. With «Усі рахунки», an account within 1 % of a firm limit is shown first in «Ліміти», in red (branch `ctrader/firm-alerts`).

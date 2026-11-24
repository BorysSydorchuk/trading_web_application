# CLAUDE.md: Orchestrator instructions

You are the **lead engineer / orchestrator** of the Trading Journal app.
The product owner is Borys (a trader). The product manager is a separate ChatGPT chat; Borys pastes its reviews here.
Claude Code is the only active agent; Codex is paused since 2026-11-16.

## Active owner override — 2026-11-16 (Claude Code resumes; supersedes the 2026-11-14 Codex handoff)

- Claude Code is the lead engineer/orchestrator, the only active agent, and the sole
  owner of merges to `main` (`git merge --no-ff`). Codex is paused: it works only on
  `codex/<topic>` branches when Borys explicitly asks, and never merges.
- Keep the S/M/L tiers below: targeted tests during work, one full `make check` on the
  final commit before merge, `code-reviewer` (specialists for L), pre-migration backup.
- Never push or force-push. Borys pushes. End every report with
  `main готовий до push: <sha>`.
- No live AI (Claude API) or Whisper runs without Borys's explicit permission and a
  call budget; log every call. MT5 strictly read-only: no `order_send` / `order_check`.
- Trading-hours load rule (owner/PM 2026-11-19): Borys trades weekdays 08:00-16:00 Brussels.
  Gate rule (owner 2026-11-24, this laptop): the full gate always runs with pytest -n 2 and
  vitest --maxWorkers=2, and first checks free RAM; under 3 GB it re-checks for up to 10 min,
  then reports instead of starting. Both are the default of plain `make check`. Never run
  backfills, Whisper or other heavy jobs in trading hours without asking. Never ask Borys to
  close TradingView or other trading tools. Raise a test timeout only per test, with a reason.
- Current gate: M8 started with M8-11 only (see `docs/M8_BACKLOG.md`); every other M8
  item needs separate PM authorization.

## Read first, every session
1. `docs/PRD.md`: what we build and why (source of truth for product decisions)
2. `docs/ROADMAP.md`: milestones and acceptance criteria
3. `docs/STATUS.md`: where we stopped (create it if missing)
4. `docs/DECISIONS.md`: technical decisions already made (create it if missing)

## Change tiers (PM 2026-11-12: right-size the workflow; overrides the delegation and review lines below where they differ)
Classify every task at the start and write the tier next to it in `docs/STATUS.md`.
- **S (small):** <= ~3 files, no migration, no money/risk math, no MT5 calls (UI text, a filter, a config option, a bug in one function). Do it yourself, no subagents. Only affected tests while working; one full `make check` before merge; one `code-reviewer` pass. Report: 3-5 lines. Target 15-30 min.
- **M (medium):** new endpoint/page, several modules, no data migration. Max 2 subagents. Targeted tests while working; one full `make check` before merge; one `code-reviewer` (re-review only after CHANGES REQUESTED). Short report.
- **L (large / risky):** DB migrations, money/risk/lot/P&L math, MT5 sync/worker, anything touching real data. Full process: tests first (`tdd-guide`), specialist reviewers (`database-reviewer`, `python-reviewer`), pre-migration backup, detailed report in `docs/reports/`.
- All tiers: the full suite at most twice per task; during work use `pytest <path> -k ...` and `npx vitest related <files>`. The last full `make check` must run on the final commit before merge: if review fixes come after a full run, spend the second full run after the fixes, not before. Never merge on targeted tests only (PM 2026-11-13). Exception (PM 2026-11-17): a docs-only merge (no code, config, tests or migrations changed) may skip the full `make check`; any other change still needs the full check on the final commit. One general `code-reviewer` by default; specialists only for L. Subagents get a short brief with only the files and PRD sections they need, not "read all docs". Owner live checks: guarded live-check scripts only for L milestones; for S/M give Borys 2-3 click steps.
- Chat reports to Borys: max ~15 lines (what changed, what he must do, open questions). Details go to `docs/reports/`.

## How you work
- Work **one milestone at a time**, in ROADMAP order. Do not start the next milestone until the current one passes its acceptance criteria.
- Split the milestone into small tasks (each roughly 1 to 3 files, testable). Track them in `docs/STATUS.md` as a checklist.
- Delegate:
  - `backend-dev`: Python, FastAPI, DB, MT5, AI integration
  - `frontend-dev`: React UI
  - `qa-tester`: writes and runs tests, reproduces bugs
  - `code-reviewer`: reviews every finished task before you mark it done
  - `tdd-guide` (with the `tdd-workflow` skill): required for position-size, risk-limit, P&L and R calculation code
  - `database-reviewer`: required for every Alembic migration
  - `python-reviewer`: specialist Python review, tier L only
  - `security-reviewer`: one pass before M7 Hardening is accepted; not on every task
- Before calling a reviewer agent, run the checks yourself and pass the diff (git diff) and changed file list in the prompt.
- Independent tasks (for example backend endpoint + frontend page against an agreed API contract) may run in parallel. Agree the API contract first and write it into `docs/api.md`.
- After each task: run `make check` (lint + type check + tests). Never mark a task done with failing checks.
- Commit after every completed task with a clear message (`feat(sync): ...`, `fix(ui): ...`). Small commits.
- **Start of every session:** run `git status` and `git log --all --oneline -20` and compare with `docs/STATUS.md`. Report anything unexplained (unknown commits, untracked files, code not described in STATUS) to Borys before building on it.
- **One agent session per checkout (owner/PM 2026-11-19):** only one agent session works in this checkout at a time. Parallel work uses a separate git worktree: `git worktree add ../WEB_application-<topic> <branch>`. At session start, if the checkout has uncommitted changes you did not make or the branch changed unexpectedly, stop and report to Borys; do not delete or switch anything. Never `git switch`/`checkout` in a checkout another session may be using.
- **Codex (OpenAI) and any other non-Claude-Code agent** (paused since 2026-11-16; works only when Borys asks; its instructions: `AGENTS.md`):
  - Works only on its own branch `codex/<topic>`, one task at a time; the task is listed in `docs/STATUS.md` with owner `codex`.
  - Never merges to `main`. The orchestrator reviews its branch like a subagent task: `make check`, `code-reviewer` (plus the required specialist reviewers), then `git merge --no-ff`.
- **Pre-migration backup:** before any `alembic upgrade` on the dev database `trading_journal` (`make db-ensure`, `start.bat`, `make migrate`, anything), a `pg_dump` goes to `backups/pre-migration-<revision>-<timestamp>.dump` and its path is printed; keep the last 10. Tests on `trading_journal_test` do not need this.

## Git workflow
- M0 and M1 live on `main`. From M2 on, one branch per topic: `m<N>/<topic>` (for example `m2/terminal-path-guard`), created from up-to-date `main`. Commit the topic's tasks there.
- Merge a topic branch into `main` with `git merge --no-ff` only after code-reviewer APPROVE and a green `make check`.
- **Never push** (no `git push` of any branch, no force-push). Commit and merge locally only; Borys pushes himself. This overrides any push step in `.claude/rules/ecc/` or older notes.
- Borys pushes, you never push. After every merge to `main`, end your message to Borys with exactly one line: `main готовий до push: <commit>`.
- Each milestone report (`docs/reports/M<n>.md`) lists the milestone's commit range.

## Decisions and questions
- The PRD answers product questions. **Do not ask Borys to re-confirm decisions written in the PRD.**
- For technical choices not covered by the PRD: pick the simplest robust option, record it in `docs/DECISIONS.md` (one line: date, decision, reason), continue.
- Ask Borys only when you are blocked by something only he can provide (credentials, a trading rule that is truly missing, access). Batch such questions into one message.

## End of milestone
1. All acceptance criteria in ROADMAP met and checked by running the app, not only by tests.
2. Write `docs/reports/M<n>.md`: what was built, how to run it, what was tested, known issues, open questions for the PM, assumptions made.
3. Stop and tell Borys: "Milestone M<n> done, report in docs/reports/M<n>.md". He will bring the PM's review back.

## Hard rules
- Secrets only in `.env` (gitignored). Never print tokens or passwords in logs or commits.
- Do not read or edit `.env`, `.env.*` or `secrets/**`, and never print credentials. Authorized tests may load application settings internally.
- Explicit `encoding="utf-8"` for all file I/O (existing BOM-tolerant reads remain valid). No PowerShell text editing of config files.
- Owner checklists: exact Ukrainian UI names and click paths, one line per item; commands run from normal PowerShell in the repo root.
- All timestamps stored in UTC. Convert to Europe/Brussels only in the UI and in session logic. MT5 server time is NOT UTC; convert explicitly (see PRD 6.3).
- MT5 access is read-only. The app never opens, modifies or closes positions.
- UI text is Ukrainian. Keep all strings in one i18n file (`frontend/src/i18n/uk.ts`), no hardcoded strings in components.
- No feature creep: if you see a useful idea outside the milestone, add it to `docs/BACKLOG.md` and move on.
- When ECC rules in .claude/rules/ecc/ conflict with CLAUDE.md, the Makefile or pyproject.toml, those win.
- Errors must be visible: failed sync, failed transcription, failed AI call show a clear message in the UI and in `logs/`, never a silent failure.

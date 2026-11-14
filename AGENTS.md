# Trading Journal — Codex workflow

## Active owner override — 2026-11-14 (tier S handoff)

While Claude Code is paused, Codex is the lead engineer and the only active agent.
The PM is a separate ChatGPT chat; Borys pastes its reviews here. This section
supersedes conflicting delegation, independent-review and Codex merge restrictions below.

- Work one task at a time on `m<milestone>/<topic>` from up-to-date `main`; record
  its owner and S/M/L tier in `docs/STATUS.md`. Do not spawn other agents.
- Use targeted tests during work. Commit the final change, run the complete
  `make check` on that final commit, self-review against the PRD and the checklist
  in `.claude/agents/code-reviewer.md`, then merge locally with `git merge --no-ff`.
  Never merge a failing or unreviewed change. Preserve tier L financial TDD,
  migration/specialist checklist coverage and pre-migration backups, performed
  by the sole active engineer while this override applies.
- Never push or force-push; Borys pushes. End every report with
  `main готовий до push: <sha>`. If Claude Code resumes, Borys names the merge owner.
- No live AI (Claude API) or Whisper runs without Borys's explicit permission
  and a call budget; log every call. MT5 is strictly read-only: no `order_send`
  or `order_check`. Secrets stay in `.env`; the secret-file access prohibition below remains.
- Preserve Decimal financial math, UTC storage, Europe/Brussels sessions and UI
  strings in `frontend/src/i18n/uk.ts`. Use explicit `encoding="utf-8"` for file I/O
  (existing BOM-tolerant reads remain valid). No PowerShell text editing of configs.
- Reports: at most about 15 lines in Ukrainian-friendly plain English or Ukrainian;
  details in `docs/reports/`. Owner checklists use exact Ukrainian UI names and
  click paths, one line per item; commands run from normal PowerShell in the repo root.
- M6-08 QA is merged at `9758e4d`. Wait for the [OWNER] checklist in
  `docs/reports/M6-live-check.md` and the PM verdict on AI summary text; then fix
  findings, finish `docs/reports/M6.md`, report M6 done and wait for PM review before M7.

Read `CLAUDE.md`, `docs/PRD.md`, `docs/ROADMAP.md`, `docs/STATUS.md`, and
`docs/DECISIONS.md` before work. They remain authoritative; latest explicit owner/PM
decisions supersede older progress notes. Read `docs/api.md` for implementation.
Preserve the architecture, Ukrainian UI, Decimal financial math, UTC storage and
Europe/Brussels sessions. Never push or operate real trading accounts.

## Preserved instructions

- Read `.claude/rules/dependencies.md` and all `.claude/rules/ecc/common/*.md`.
- For Python, also read `.claude/rules/ecc/python/*.md`; `fastapi.md` applies to
  app/API code. CLAUDE.md, PRD, Makefile and pyproject.toml win over generic ECC
  examples. Missing ECC links are not additional requirements.
- Each specialized agent reads `.claude/agents/<role>.md` and follows its full
  body. Claude model/tool headers are metadata: Codex models are configured in
  `.codex/`; use native read/search/edit/shell tools within the role's limits.
- Existing skills remain at `.claude/skills/<name>/SKILL.md`: cost-aware-llm-pipeline,
  postgres-patterns, python-patterns, python-testing, regex-vs-llm-structured-text,
  security-review, tdd-workflow. Read applicable skills and relative resources.
  These are explicitly referenced resources, not automatically discovered skills.
- Do not read or edit `.env`, `.env.*`, or `secrets/**`, or print credentials.
  Existing application settings may load environment configuration internally for
  authorized tests; expose only non-secret database target metadata.
  Dependency additions require owner approval. No repeated Whisper runs without
  owner approval; keep documented run limits and live-check gates.

## Coordination

- One main orchestrator (`gpt-6-astra`); every subagent `gpt-6.1-sol`, including
  explicit spawn overrides. Never silently substitute a model. When the runtime
  cannot select a configured role, pass that role's instruction path explicitly
  and spawn with the required model and a fresh context.
- Assign exclusive file ownership before parallel edits. Serialize overlapping
  changes. Use separate worktrees only when isolation benefits independent work.
- One designated runner owns full integration verification and database tests.
  Other agents must not run `make check`, pytest, migrations or database resets
  concurrently. Check actual database name/host and active users before resets;
  never target dev/production/real trading data. Do not delete QA databases
  without owner authorization.
- Run the complete Makefile checks before requesting independent code review.
  Give reviewers the full diff, changed-file list and verification evidence;
  reviewers do not run git, tests or modifying commands. General review is
  required for every task; migration review and financial TDD remain mandatory
  where CLAUDE.md requires them.
- Branch and merge rules (PM, 2026-11-09; supersede older merge instructions):
  work only on your own branch `codex/<topic>`, created from up-to-date `main`, one
  task at a time, and only on a task listed in `docs/STATUS.md` with owner `codex`.
  Commit completed work there with repository conventions. **Never merge to `main`**:
  the Claude Code orchestrator reviews the branch (make check, code-reviewer and the
  required specialist reviewers) and merges it with `--no-ff`. Preserve unrelated
  changes you did not make.
- At the start of every session: `git status` and `git log --all --oneline -20`,
  compared with `docs/STATUS.md`; report anything unexplained to Borys first.
- Before any `alembic upgrade` on the dev database `trading_journal` a pre-migration
  `pg_dump` backup is required (see CLAUDE.md); `trading_journal_test` is exempt.
- Track progress in existing docs. Owner acceptance of a milestone comes only from
  Borys.

## Usage checkpoint and safe shutdown

Check reliable remaining 5-hour usage at milestone boundaries, before expensive
operations and before additional agents. If unavailable, say so and ask the owner;
never estimate it. At 15% prepare shutdown and avoid large tasks. At 10% or less,
owner stop request, or imminent exhaustion: stop assigning work, stop agents after
immediate safe operations, cancel/finish controlled background processes, preserve
all changes, and make no destructive DB operations. Commit only fully verified and
reviewed work. Write a timestamped checkpoint in docs/STATUS.md with current task,
Git state, checks, agents, DB/resources, blockers and prioritized next steps. Include
RESUME FROM HERE with exact action, files, operations not to repeat and next PM gate.
Report briefly, then stop; do not auto-resume after reset.

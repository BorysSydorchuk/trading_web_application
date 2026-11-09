# Trading Journal — Codex workflow

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

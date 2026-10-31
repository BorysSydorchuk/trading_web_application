Paste this into Claude Code as the first message, from the repo root:

---
You are the orchestrator for this project. Read CLAUDE.md, then docs/PRD.md and docs/ROADMAP.md fully.
Then:
1. Create docs/STATUS.md, docs/DECISIONS.md, docs/BACKLOG.md and docs/api.md (initial contract for M0/M1).
2. Plan milestone M0 as a checklist of small tasks in docs/STATUS.md.
3. Execute M0 by delegating to the subagents in .claude/agents (backend-dev, frontend-dev, qa-tester, code-reviewer). Run independent tasks in parallel.
4. Commit after each approved task.
5. When M0 meets its acceptance criteria, write docs/reports/M0.md and stop.
Do not ask me to confirm anything that is already decided in the PRD. If you need something only I can provide, collect all such questions into one message.
---

For the next milestones: "Read CLAUDE.md, docs/STATUS.md and the PM review below, then do milestone M<n>." + paste the PM review.

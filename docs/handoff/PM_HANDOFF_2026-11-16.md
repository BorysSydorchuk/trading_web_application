# Trading Journal — Complete AI/PM Handoff

**Prepared:** 2026-11-16 (Europe/Brussels)  
**Purpose:** Enable a replacement AI agent to take over product management, Codex review, M8 planning, UI/UX research coordination, and acceptance without having to reconstruct the chat.  
**Project language:** Ukrainian UI and generally Ukrainian PM/owner communication. Technical prompts for Codex or research agents are usually in English.  
**Authoritative repository sources:** `AGENTS.md`, `CLAUDE.md`, `docs/PRD.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/STATUS.md`, `docs/BACKLOG.md` (verify exact name/path), and `docs/reports/`. **Read these from the actual repository before making changes.** This handoff describes reported results; it is not a substitute for examining the repository.

## 1. Immediate executive handoff

- The owner has **accepted and closed the M7 technical milestone**. Milestones **M7-01 through M7-07** received technical and owner acceptance. The previously planned M7-08 five-real-trading-day gate was **superseded, not completed**. **0/5 live trading days** were recorded at closure; their validation/feedback is transferred into M8. Never say these five days passed.
- **M8 — UX & Functional Improvements** has been **authorized for planning and requirements collection only**. No M8 implementation has been authorized, and no M8 feature code has been written as part of this handoff. The owner is dictating fixes, wants them retained as an organized backlog, and will keep giving screenshots/feedback during ordinary app use.
- **Last reported local `main` commit:** `8e2221179d1a7071d3b1381a2717978c83812620` (M7 closure/documentation decision). Local merge `--no-ff` and clean test report, **no push performed by Codex**. The owner may or may not have pushed since; check `git status`, `git log`, and remote before claiming push status. An older `m7/trading-week` branch with preparatory commit `8b6ade5` was **preserved without merging**; it contains a day-by-day live-use checklist/report template.
- **M8-10 UI/UX research brief has been drafted** for a separate research agent (potentially Fable). The owner wants actual competitor research, three visual directions, a strong professional dark theme, design system, branding/logo, and a concrete designer/engineering handoff, **research first, no code**. This parallel discovery can begin independently of implementation, but selection of direction remains an owner decision.
- A screenshot shows an **intermittent severe layout/overscroll defect**: the status/footer bar appears in the middle of the browser viewport with a large blank region below. Included as `M8-11_footer_overscroll_evidence.png`. Do not assume the exact CSS cause before investigation.
- Next agent should **continue collecting owner feedback**, not immediately issue an unrestricted Codex implementation prompt. Resolve ambiguities, prioritize/sequence M8 requirements, preserve MT5 source-of-truth records, and obtain explicit PM/owner authorization per task or batch.

## 2. Role, workflow, and response conventions

- Act as the product manager and reviewer; **do not personally implement application code** in this PM interaction. Codex CLI is currently the sole lead coding agent; another AI/design agent can conduct UX research. User decides product behavior and performs final owner checks.
- Reply **briefly and directly in Ukrainian** for project-management conversations. When assigning Codex work, provide **one fully copy-ready English fenced code block** beginning with a PM verdict and numbered implementation/verification requirements. Do not scatter separate prompts.
- Review Codex completion reports against repository product truth, owner decisions, test evidence, and exact checks. Distinguish: `TECHNICAL ACCEPTED`, `OWNER ACCEPTANCE PENDING`, `ACCEPTED`, `CHANGES REQUESTED`.
- The agent must end completion reports with exactly `main готовий до push: <sha>`. **Codex does not push**. Owner does `git push origin main` after acceptance; remind only if not known to be done.
- Preserve the working tree, existing branches, worktrees, stashes, dev/QA databases, backups, logs, and real trades. First inspect `git status`, recent history, branches/worktrees/stash. Do not remove files or recreate DBs to make tests pass. No unauthorized live MT5 actions, paid AI/Whisper calls, or secret disclosure.
- Tier rules: **S** only for a small change (normally <=3 files) with no DB migrations, financial math, or MT5; **M** medium; **L** for schema/migrations, money calculations, MT5/real-data risk, major security/integration work. Follow `AGENTS.md`/`CLAUDE.md` as canonical. For L, require rigorous tests, isolated synthetic validation, reviews; `make check` on final task commit before local `git merge --no-ff`. Do not start subsequent tasks without PM acceptance.
- Keep UI labels and owner click paths Ukrainian. Owner checks should be concrete, brief, and reportable PASS/FAIL. Never ask owner to perform destructive restore or reproduce malicious behavior against real data when synthetic evidence suffices.
- If Codex loses context, have it audit the Git tree and local history instead of restarting work blindly.

## 3. Product and operational context

**Product:** Local-first, single-owner desktop web trading journal for discretionary Forex/CFD and funded-account trading on Windows. Frontend React/Vite (Ukrainian); backend FastAPI/Python; PostgreSQL 16 (Docker or native); separate worker; launcher `start.bat`, `stop.bat`; default local frontend `http://127.0.0.1:5173`, API `127.0.0.1:8000`. MT5 synchronization is **strictly read-only**: reads history/open positions/specs and calculates margin/profit; never opens/modifies/closes orders. Multiple funded MT5 accounts; portable terminal copies configured per account. AI (Claude) and voice (Whisper) are optional and have cost/privacy implications. Secrets belong only in local `.env` and should never appear in chat, reports, Git, or screenshots.

**Pages:** `«Головна»` (performance, risk, open positions, sync, pending actions); `«Журнал»` (trades, filters, columns, descriptions, rule violations); trade description workflow; `«Біас»` (context and alignment); `«Калькулятор»` (position sizing); `«Дайджести»` (weekly/monthly review); `«Налаштування» → «Рахунки»`; bottom status bar with API/DB, backups, MT5 sync and alerts.

**Important business/trading rules to preserve unless owner updates:** London entries 08:00–11:00 Brussels; 11:00–13:00 premarket no entries; NY 13:00–16:00 Brussels. Fixed $10,000 reference account for 1% risk/trade; daily -3%/+5%; weekly -6%/+10%; maximum 10 trades/week; minimum RR 1.5; no moving to breakeven; re-entry maximum once; QM model not allowed in NY. Symbols EURUSD, GBPUSD, XAUUSD, GER40 (`GER30` MT5 alias). GER40 contract 10, tick 0.01, EUR tick value 0.1 EUR converted using EURUSD ask; round lots down. Any change to financial calculations is Tier L and must be precise/Decimal-safe.

**M7 backups:** daily 18:00 Europe/Brussels with DST handling; one catch-up on startup after a missed scheduled time, not replay of all days; persistent deduplication/locks. Retention = union of 14 daily + 8 weekly + 6 monthly representatives from verified daily archives. Manual and pre-migration backups are protected from automatic cleanup. Atomic `pg_dump`, full `pg_restore` archive inspection and SHA-256 manifest; restore first to a **new empty isolated database**, never overwrite live/QA DB. Backups on same disk do not protect from physical disk loss. M7 logging rotates standard API/worker logs, **not** `logs/ai_usage.jsonl`.

**Known earlier deferred owner checks/backlog:** Prior M3/M4 voice/digest/Bias owner follow-ups were tracked separately; the previous PM context mentioned M3 checks 9–12, some M4 reminders/voice bias questions, duplicate time helpers and Ctrl+C prompt improvements. Consult current repository BACKLOG/DECISIONS rather than assuming these were closed. Do not let M8 planning silently delete them.

## 4. Historical M0–M7 work and review outcomes

### Milestones before M7

- **M0–M6:** reported **ACCEPTED**. Prior work delivered core journal/trade tracking, MT5 sync, Bias, rules/position calculator, digests/optional AI, and related UX. The M6 ending reference was reported as `1a194a9` (verify repo history).
- M5 Decimal sizing core previously had 97 passing tests and 97% targeted coverage during development; final subsequent milestone gates are broader. All financial results should remain safeguarded.

### M7 hardening (each task accepted)

| Task | Reported scope and acceptance evidence |
|---|---|
| **M7-01 [L]** | Atomic verified database dump + SHA-256, isolated synthetic restore, safe retention 14/8/6 union; protected manual/pre-migration, separate DB targets; owner accepted. Reported commit `4dc0ac5`. |
| **M7-02 [L]** | Daily 18:00 Brussels scheduler, DST, one startup catch-up, bounded retries, restart dedupe and Ukrainian backup status; owner 6/6 checks accepted. Commit `4896c86ecf41eef792da67ea8970a365263ecdcd`. |
| **M7-03 [M]** | UTF-8 UTC logs, credential redaction, Windows multiprocess-safe rotation (5 MiB + 5 archived files per API/worker file); AI audit untouched. Owner 3/3 PASS. Commit `85d6ac8370eab94395e565f9e008416b0cc35ecc`. |
| **M7-04 [M]** | Preflight/startup safety: versions, backend/frontend/worker readiness, DB identity, backup tools and verified pre-migration backup, safe process ownership. Owner 3/3 PASS. Commit `55be22b6749eeb7816fff195ef2fba18a6b7297c`. |
| **M7-05 [M]** | Performance baseline and bounded journal optimization. Representative synthetic dataset 1,040 closed trades, 2 accounts, year-long. Warm startup p95 **7.83s** (<10s); optimized Journal p95 **283.1ms** (<300ms), median 262.15ms; a single >300ms raw sample is not a p95 violation. Initial full check twice hit an unchanged flaky digest test; owner/PM granted one-time third final gate, resulting in **3289 backend PASS** + intentional 1 Whisper skip, **481 frontend PASS**. Owner 3/3 PASS: journal column persistence, sorting/description, benchmark. Final main `104245087359d9e3a052d7304e3b12375e286ecb`. |
| **M7-06 [S]** | README fresh Windows installation, setup from repository root, Git/Python 3.12/Node/uv, Docker PG16/native alternative, `.env`, MT5 portable, start/stop, offline operation, backups, troubleshooting; isolated install/UI/shutdown PASS. Native PostgreSQL full install and fresh Windows VM **not tested**, transparently documented. **3289 backend PASS, 481 frontend PASS**, self-review APPROVE. Owner 3/3 PASS. Final main `3ede8b2b326b7b001ad229ab8687bcf4660e9837`. |
| **M7-07 [L]** | Security/safety audit and integrated QA. Fixed **HIGH** foreign Host/Origin request vulnerability (ASGI local boundary; rejects foreign/malformed/duplicate Host, mismatched Origin and cross-site Fetch Metadata) and **MEDIUM** iframe exposure (`X-Frame-Options: DENY`, CSP frame-ancestors none, nosniff). Windows locks/redaction and fixture integration PASS. Synthetic restore verified **17 tables, 96 constraints, 43 indexes**, source 1,040 closed + 2 open trades, with canonical checksums and invalid-write rejection. **3317 backend PASS**, 1 expected Whisper skip, **482 frontend PASS**, self-review APPROVE; owner **5/5 PASS**. Final main `c9dc7c29a29604dbfc222bdc756729b51f37d511`. |

**M7-07 deferred security findings (nonblocking, BACKLOG):** `AUD-03` approximate AI $5–7/month planning budget has no enforced hard monthly cap (owner/PM policy needed); `AUD-04` 7 **moderate**, zero high/critical, npm advisories in ESLint/typescript-eslint/minimatch dev chain (no forced upgrade); `AUD-05` low-risk audio upload root/junction policy under trusted local filesystem; `AUD-06` AI audit file process-local locking/growth/durability limitations (do not rotate/delete it); `AUD-07` development package engine warning (jsdom and transitive dependencies on host Node 24.14.1 despite passing install/tests). No claim of complete Python advisory scan, OS security, multi-user remote deployment, or live AI/MT5 validation.

**M7-07 owner checks all passed:** UI/backup status on launch; Journal filters/columns/trade details; Bias/Digests/Calculator/Accounts; header `DENY` and foreign-Origin API `403`; stop/restart and data persistence. Real-data restore was **not** requested; synthetic evidence sufficed.

### M7-08 change of plan and final closure

1. Originally authorized five distinct **real trading days** of owner-use verification with checklist A–F (Dashboard/sync/risk/backups; describe closed trade if available; Journal; Bias; Calculator; Digests). No fabricated trades; dated evidence; no AI without approval. This was an **acceptance plan, not a completed test**.
2. Codex prepared a checklist and report template `docs/reports/M7-08.md` on branch `m7/trading-week` as commit `8b6ade5`. It explicitly reported **0/5 days**, no merge/push, no runtime/data changes.
3. Owner then decided to **close the M7 technical hardening milestone without blocking on a five-day live trial**, because real usage would continue while collecting issues for M8. PM approved this scope change: **M7 CLOSED; M7-08 SUPERSEDED (not ACCEPTED); 0/5 live days transferred to M8**.
4. Codex updated `docs/ROADMAP.md`, `docs/STATUS.md`, and `docs/DECISIONS.md`; preserved M7-08 branch/commit/template without merging; full gate **3317 backend + 482 frontend PASS**, review APPROVE, local `--no-ff` merge. **Latest reported main `8e2221179d1a7071d3b1381a2717978c83812620`.** No M8 implementation started; Codex did not push.

**Accuracy requirement:** Do not call M7-08 passed or say five live days happened. “M7 technical milestone accepted” and “live validation pending/transferred to M8” are both true.

## 5. M8 owner-dictated issues — FULL requirements, first batch

**Status:** 11 provisional M8 entries were captured from owner dictation on 2026-11-16. Their IDs are planning IDs, not guaranteed to exist in repo files yet. Owner explicitly said more feedback/screenshots will follow. Do not replace exact requirements with generic redesign notes. Proposed details labeled *PM proposal* below still need sign-off; distinguish owner intent from design decisions.

### M8-01 — Exclude specific trades from strategy statistics (HIGH)

**Owner example:** a gold/XAUUSD trade opened on the 11th only to check whether a newly funded account could trade; it should not distort strategy/performance statistics or require a normal strategy journal description.

- Add a per-trade action such as `«Не враховувати у статистиці»` with **mandatory written reason** for exclusion.
- Owner should be able to identify/read the excluded trade later; *PM proposal*: reverse the exclusion, display excluded status and reason, keep raw MT5 sync/history unchanged rather than deleting records.
- Define whether exclusion affects win rate, net/gross P&L, trade count, RR, expectancy, setup analysis, digests, rule violations, account-level risk compliance, etc. **Important design decision:** trading-strategy statistics vs actual account risk/balance should not accidentally become falsified; specify which metrics are raw and which filtered.
- Test that re-sync does not re-include it or delete the annotation; existing historical data unchanged.
- Likely schema/stats/data behavior → Tier L; don't authorize without detailed calculation/data migration spec.

### M8-02 — Fill out an OPEN trade and complete it after closure (HIGH)

- Owner wants to record setup, emotions, reasoning and **before-entry charts while position is still open**; not only after it closes.
- Persist partial description on the open position and allow subsequent additions/editing of the **same** record when trade closes. No loss/replacement on MT5 sync.
- Support data lifecycle OPEN → CLOSED; ensure no duplicate description, no fabricated exit data, and safe linking to source MT5 position/deals.
- Current UI/DB may be closed-trade-oriented; inspect schema and identity mappings before solution.

### M8-03 — Better before/after chart link defaults

- Owner usually attaches **1–2 charts before entry** and **1–2 after exit**.
- On adding chart links, present **two “before entry” chart fields by default** first, then after-exit links later; permit flexible counts.
- Clearly label “до входу” vs “після угоди”; retain editability on open/closed trade. Do not treat empty placeholders as mandatory links unless owner approves.
- Relationship/dependency: M8-02 plus trade description UI.

### M8-04 — Rule violation taxonomy updates

**Add** violations:
- Entry not according to the entry model (`Вхід не за моделлю входу`).
- Entry from a weak POI (`Вхід від слабкої POI`).
- Entry outside the trading system / **ignoring H1 and H4 context** (`Вхід не за торговою системою (не дотримуючись контексту H1/H4)`).

**Consolidate** existing “entry after daily stop-profit” and “entry after daily stop-loss” into a broader **daily risk violation**; also support **weekly risk violation** (owner called out daily/weekly risk). Confirm exact labels, how existing specific flags map, and whether old nuance is preserved for history/statistics. **Do not silently rewrite past records.**

### M8-05 — Independent H1 and H4 context; combinations in statistics

- Remove old single/combined “H1 synchronized with H4” context choice and replace with two independent attributes: **H1 context** and **H4 context**.
- EACH has enum: **Flow, Reversal, Range, Other**.
- `Other` requires explanation (mandatory free-text when selected).
- Owner-described examples of combinations: Flow H1/Flow H4, Reversal H1/Reversal H4, Flow H1/Reversal H4, Flow H4/Reversal H1. All combinations including Range become possible naturally.
- Stats should be able to analyze **H1×H4 combinations**, not just a prior boolean/single selection.
- Decide how old values migrate/display and avoid lossy guesses; schema/data-change Tier L.

### M8-06 — Multi-select POI types and fractal options

- POI can simultaneously be **FVG H1** and **FVG H4** and potentially other categories; current single-choice limitation is wrong.
- Keep existing POI choices, **add Fractal H1 and Fractal H4**, allow **multiple selections** for one trade.
- Support `Other`; use mandatory description wherever “Other” is selected (consistent with user's general requirement).
- Historical POI values must remain accessible after migration, statistics/filter semantics defined.

### M8-07 — Multi-select and conditional FVG type

- FVG type may **both refresh/update a fractal and be a manipulation**: multiple selections allowed.
- Show “FVG type” question **only if POI includes FVG H1 and/or FVG H4**. Hide it otherwise. Define whether hidden values are preserved or cleared if user deselects FVG; avoid silent data loss.
- No forced FVG-type field for trades with no FVG POI. If user wants H1 and H4 FVG each with different classifications, clarify whether one combined FVG-type set or per-timeframe fields are needed.

### M8-08 — Entry model stays SINGLE-select; “Other” explanation

- Owner explicitly said the one-entry-model selection is correct.
- If `Інше` selected, **require a text description** of the actual model. Otherwise preserve current model choices and logic.

### M8-09 — Infer exit reason from existing trade prices

- If realized **exit price** matches **initial stop-loss**, suggest/fill `Stop Loss`; if it matches **take-profit**, suggest/fill `Take Profit`.
- When neither matches, user chooses reason manually. *PM safety proposal*: never overwrite an explicitly entered reason; allow manual override of inferred value.
- Implement instrument-appropriate price tick/precision tolerance, handle partial exits/multiple deals, modified TP, slippage and gaps carefully. Do not equate approximate proximity blindly or assume reason is known solely from close price; evaluate whether existing MT5 deal reason is a more reliable source. Owner asked for automation but exact matching logic must be specified/verified.
- Financial/trade interpretation risks → likely Tier L.

### M8-10 — Comprehensive UI/UX research + redesign + branding/logo (HIGH discovery)

- Owner says current UI is poor and wants research-driven, professional-grade redesign; **assign a separate research/design agent**, potentially **Fable**, to analyze existing screens and other trading journals, then deliver a detailed implementation brief. User will supply screenshots.
- Research current practice among **TradeZella, TraderSync, Edgewonk, TradesViz, Tradervue, TradingView, Notion journal solutions and at least one other**. Evaluate real interfaces, patterns, hierarchy, table density, filter/navigation efficiency, form flows, status/error states, typography/spacing, dark theme, accessibility, desktop responsiveness. Cite links/source/screenshots and clearly distinguish observations from assumptions.
- Produce **three distinct visual directions** with pros/cons, color HEX palettes, typography, spacing and layout concepts; recommend one with rationale. Strong professional dark mode; no default generic admin dashboard, overdone gradients/glassmorphism, clutter.
- Detailed **design system**: semantic colors, readable P&L/warning state, spacing and typography tokens, cards/tables, nav, modals, tooltips, chart/image attachments, multi-select/conditional forms, keyboard usability, dense data, fixed vs scrollable areas.
- Design **three branding/logo concepts**, including app icon/favicon and wordmark, with distinctive approach (not a generic rocket/$/candle icon).
- Redesign page by page: Dashboard, Journal, trade description, Bias, Calculator, Digests, Settings, system/footer status. Preserve workflows/functionality and Ukrainian copy. Separate visual-only changes vs frontend UX behavior vs backend/schema changes.
- Required deliverable content: executive summary, screenshot-based current UX critique, competitor table, top 15 improvements, three directions, recommended direction, IA, page specs, design system, three brand concepts, prioritized implementation plan with P0/P1/P2 and S/M/L, risks/tradeoffs, open owner decisions, **ready-to-use Fable design brief**, **Codex engineering handoff**.
- **Research ONLY; no code, data, real API calls, or fabricated research claims.** Current full research prompt was previously given in chat; the above is its functional content. Owner is currently looking for an appropriate agent to run it.

### M8-11 — Intermittent overscroll / footer floating mid-page (HIGH bug)

- Owner reports that occasionally after switching/opening a page, the entire page scrolls abnormally far down, beyond intended content. Bottom status bar (server/backup/sync/version/last-check) then appears around the **middle of the browser viewport**, with a huge blank dark space below.
- Screenshot evidence: `M8-11_footer_overscroll_evidence.png` (1920×1128). The visible header/browser and lower part of `«Головна»` show open positions and status bar near y≈470, with dark empty area to bottom of captured browser. This is an **observed symptom, not a proved CSS root cause**.
- Investigate viewport/root height, `html/body/#root`, nested scroll containers, sticky vs fixed footer, min-height/flex/grid, route transitions, virtualized areas, browser zoom and resize. Do not assume a specific culprit.
- Acceptance: no spurious page scroll/empty area; footer stays in its intended place across routes, different window sizes, short/long content, refresh/restart; main content remains accessible and no horizontal overflow. Regression browser tests where practical.
- Can be addressed independently of major redesign if bug harms daily use; coordinate to avoid throwaway work.

### Provisional sequencing (not yet finalized)

- **Early, correctness/workflow:** M8-01, M8-02; require schema/financial impacts and careful data preservation.
- **Description taxonomy/forms:** M8-04 through M8-09; bundle logically if the migration and UI forms intersect, but avoid one enormous unreviewable change.
- **Urgent UI bug:** M8-11 can be an isolated scoped fix once repro/root cause found.
- **Parallel design research:** M8-10; owner picks direction **before** redesign implementation.
- **M8-03** pairs with open-trade description workflow M8-02.
- These are initial priorities, not commands to implement. Final priority depends on owner feedback and constraints.

## 6. UI/UX agent assignment: short copy-ready brief

Use the following as a standalone prompt to start research (the full, longer version was sent previously in conversation). Attach current screenshots of all main pages and the footer defect image.

> You are a senior product designer, UX researcher, and design-systems architect specializing in financial/trading applications. Research, do not code. Trading Journal is an existing Windows local-first FastAPI/PostgreSQL + React/Vite application, UI in Ukrainian, for a discretionary Forex/CFD trader with multiple funded accounts. Analyze provided current screens, including Dashboard, Journal, Description, Bias, Calculator, Digests, Settings and bottom system status. Study at least eight comparable tools: TradeZella, TraderSync, Edgewonk, TradesViz, Tradervue, TradingView, Notion journal patterns and one other. Use current verifiable visual sources and links; distinguish fact from speculation, do not fabricate screenshots/interviews. Diagnose usability issues including dense tables, poor information hierarchy, navigation, long forms, scrolling and footer overflow (do not assert root cause without code). Optimize before-entry, open-position journaling, after-close completion and weekly review. Propose three different credible dark-theme visual directions with HEX palettes, typography, spacing and tradeoffs; choose and defend a recommendation. Specify page-by-page wireframe-level requirements, information architecture, accessible design tokens and components (especially data tables, multi-select/conditional forms, trade charts, state/status/error handling). Propose three distinctive logo/brand directions, icon and favicon. Preserve existing financial/MT5/business rules, local behavior and Ukrainian UI. Separate visual-only vs frontend UX vs backend/schema proposals. Deliver an evidence-based comprehensive report with top 15 prioritized improvements, three directions, one recommendation, implementation complexity, Fable-ready detailed design brief and Codex-ready engineering handoff. Research/specification only, no code or data changes. Report in English, keep relevant Ukrainian UI labels.

**Owner’s intended workflow:** Research agent gathers evidence and prepares choices → owner/PM choose visual direction → Fable produces detailed screens/specs → Codex implements in approved scoped tasks → owner acceptance. Never assume Fable is installed/connected or that design assets already exist.

## 7. Explicit decisions and unresolved questions for next PM

1. **No deletion of raw MT5 trades** simply because an owner wants them out of strategy stats; use reversible exclusion with reason as proposed, but confirm exact metrics and data-model behavior before implementation.
2. **Source-of-truth and safety:** real account P&L/risk/dashboard balances may need to remain based on all real trades even when strategy statistics omit a test trade. Define clearly with owner, preferably separate “All account activity” vs “Strategy-only” views.
3. **Open trade identity:** verify MT5 data mapping and lifecycle before adding description editing during live positions; prevent sync duplication or history loss.
4. **Migrations:** contexts, POI, FVG and rules require compatibility plan for existing values, filters, digests, bias/correlation, exports and historical entries. Never silently infer new details from old records.
5. **FVG semantics:** clarify whether type classification is linked per FVG timeframe or applied collectively to a multi-select POI.
6. **Exit reason:** initial SL/TP comparison may be unreliable with slippage/partials/modified orders; inspect recorded MT5 close reason/transactions before choosing safe inference.
7. **Visual system:** owner must select a design direction. Research may run in parallel; no design implementation authorized yet.
8. **Live validation:** continue normal usage; log date and observations. Old target of five distinct trading days was moved to M8; no evidence collected so far in this handoff. Don't misstate it as completed or as a hard M7 gate.
9. **Security backlog:** monthly AI spend cutoff/approval policy requires owner decision; npm dev advisories, audio root/junction, audit file growth, Node engines remain deferred not erased.
10. **Git state:** check whether `8e22211` has been pushed and verify branch existence; don't merge `m7/trading-week` into main without an explicit new plan.
11. **Screenshots:** additional screenshots and design brief might arrive in later conversation. Compare new user-reported issues against M8 IDs, dedupe and add new entries without losing nuance.

## 8. Concrete next actions for receiving agent

1. Read current repository docs and `docs/STATUS.md`, verify current Git reality with Codex (not by guessing from the handoff), and map the 11 M8 draft issues against any existing backlog entries.
2. Confirm to owner that **M7 closed, M8 planning active**, no coding commenced. Ask for further dictation/screenshots organically; do not require a full form or re-ask already supplied data.
3. Keep a canonical M8 backlog with ID, category, owner wording, functional behavior, acceptance criteria, priority, dependencies, tier, open questions and status. Incorporate later dictations verbatim when important.
4. When owner provides UX research output, review source quality, three directions, proposed design system, current product constraints, and completeness before approving a Fable/design implementation handoff.
5. When owner approves a task, create one numbered English Codex prompt with scope, migration/data preservation, precise acceptance tests, regressions, security, review and Git rules. Do not authorize unrelated tasks or unbudgeted AI calls.
6. For owner checklists return simple numbered Ukrainian steps and PASS/FAIL tracking. Only close each task after verification.

## 9. Source and evidence inventory

- `docs/reports/M7-07.md` — detailed security/restore report provided by owner as uploaded markdown. It recorded HIGH Host/Origin fix, MEDIUM frame fix, `AUD-03..07` deferrals, 27 boundary cases, integrated smoke, 17-table isolated restore, exact 5 owner checks.
- `README.md` from M7-06 — provided as uploaded markdown (complete setup, backups, MT5 and recovery instructions, honest limits).
- `docs/reports/M7-08.md` — prepared on the preserved `m7/trading-week` branch, not merged into `main`; use only as live-use template/evidence format.
- Screenshot `M8-11_footer_overscroll_evidence.png` — user-provided captured live local UI issue, bundled alongside this markdown.
- Current repo docs (`PRD`, `ROADMAP`, `DECISIONS`, `STATUS`, `BACKLOG`, `AGENTS`, `CLAUDE`) remain canonical for current implementation details, governance, and naming.
- The preceding chat contained the longer UI/UX research prompt; the comprehensive intent and short reusable prompt are preserved in section 6 of this file.

## 10. Safety and privacy notes

- Never request or quote real `.env` contents, account passwords, private API keys, trade-account investor credentials or private archive payloads in chats.
- During an earlier file-library inspection, a `.env`-named file with potentially real credentials was surfaced. No credential strings are reproduced here. Previously recommended owner inspect access and rotate affected credentials as appropriate. Do not open/echo such a file in a new research task.
- User-uploaded screenshots may expose account labels, times and local URLs. Keep them in private project workflow, not public reference examples without approval.
- Do not share actual private database archives. Synthetic fixture data only in external research/designer material unless owner explicitly approves otherwise.

---

**One-line state to carry forward:** **M7 technically closed and accepted; M7-08 superseded with 0/5 real days and preparatory branch preserved; `main` last reported `8e22211`; M8 planning-only with 11 concrete owner-requested issues, separate evidence-based UI/UX research plus branding, and footer-overscroll screenshot attached; no M8 feature implementation authorized.**

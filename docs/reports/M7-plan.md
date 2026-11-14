# M7 Hardening — proposed plan, pending PM approval

Plan ACCEPTED by PM. Implementation authorized for M7-01 [L] only; M7-02 requires PM acceptance of M7-01. M6 officially ACCEPTED by pasted PM review at `1a194a9`;
all owner checks and summary coverage fix verified.
Owner: codex, sole active engineer. Proposed order below; each implementation task
gets its own `m7/<topic>` branch, targeted checks, final-commit full `make check`,
PRD/checklist self-review and local `--no-ff` merge. Borys pushes.

## Baseline and boundaries

PRD 7 requires daily pg_dump and a configurable backup folder; latest PM retention
decision is 14 daily, 8 weekly and 6 monthly backups. PRD performance targets are
startup to usable UI <10 seconds and local pages <300 ms. ROADMAP also requires
log rotation, startup checks, fresh installation docs and one real owner trading week.
Existing code already has pre-migration custom-format dumps (currently keep 10), host/Docker
fallback, rotating application logs, dependency checks and API/frontend readiness waits.
Audit and extend these facilities; no dependency additions assumed.
Preserve all features, Decimal math, UTC and Brussels sessions, Ukrainian UI,
MT5 read-only access and real data. No QA database deletion or in-place restores.
No secrets in chat, logs, commits, backup metadata or reports; backups remain gitignored.
Credentials are supplied only through existing local configuration, never archive names
or metadata. No live AI/Whisper without explicit budgeted permission.
Local backups do not protect against physical disk failure; an off-device copy is
an owner operational responsibility, not an assumed cloud integration in M7.
No schema or trading-calculation changes planned; discoveries requiring these return
to PM with a revised task/tier. Specialist/security checklist reviews are performed
by the sole engineer under the active handoff override.

## Incremental tasks

### M7-01 [L] Backup service and safe retention — `m7/backups`

- Scope: reusable custom-format pg_dump operation, configurable destination, atomic
  partial-to-final publication, timeout and sanitized errors; keep 14 daily, 8 weekly
  and 6 monthly verified backups per database. Separate daily/weekly/monthly,
  manual/pre-migration and dev/QA namespaces, so QA cannot evict dev safety copies.
  Never automatically delete manual or pre-migration backups; remove the existing
  automatic pre-migration keep-10 pruning behavior as part of this task. Preserve
  legacy archives in place; no bulk moves or deletion.
- PM-approved bucket rule: successful daily archives also provide
  the latest verified representative of each Brussels ISO week/calendar month.
  Keep the union required by all three retention buckets, without additional dumps.
- AC: only complete verified archives qualify for retention; failed dumps never
  prune good backups; never delete the last verified successful backup. Retention runs
  only after successful verification. Unrelated files/symlinks and other databases are untouched.
  Verify pg_dump exit status, nonempty custom archive, pg_restore archive readability
  and a stored content checksum before publication; reject checksum mismatch on reuse.
  Archive checks do not substitute for the isolated restore/data-integrity drill.
  Missing tool, disk full, permission failure and incompatible pg_dump fail visibly.
- Automated: tests-first filesystem/subprocess tests for host/Docker selection,
  target identity, redaction, collisions, partial files, checksum corruption, timeout,
  daily/weekly/monthly boundaries and scoped retention, including last-good protection
  and permanent exclusion of manual/pre-migration archives.
  Real dump of synthetic data plus restore into a newly named isolated test target;
  verify schema/migration revision, constraints, row counts and representative values.
  Refuse existing targets: never overwrite production/dev or existing QA data.
  Preserve all existing QA databases; no database cleanup without owner authorization.
- Owner: confirm destination and free space locally; inspect archive path and successful
  restore evidence. Real dev dump is read-only and scheduled with Borys; no reset.
- Dependencies/risks: PM plan approval; PostgreSQL 16 client or existing Docker fallback;
  filesystem access, disk growth (manual/pre-migration archives are never auto-pruned),
  unsafe retention and physical disk failure. Tier L for real-data backups.

### M7-02 [L] Daily scheduling and observable backup status — `m7/backup-schedule`

- Scope: existing separate worker schedules backups daily at 18:00 Europe/Brussels,
  correctly following daylight saving time, only while the application is operational.
  On startup, after database health is confirmed, determine whether the latest due
  scheduled backup was missed and execute one catch-up if needed. Never replay each
  missed day; retain the next normal 18:00 schedule, including after a morning catch-up.
  Identify work by database and scheduled Brussels date; persistent claiming/success
  state prevents concurrent or restart duplicate execution of that scheduled backup.
  Persist success only after verified archive publication; bounded retries, no overlapping dumps,
  no blocking MT5 sync. Reuse existing health/error presentation with uk.ts strings
  for the last successful backup timestamp, failed attempts, clear errors and overdue
  status; all UI messages Ukrainian. Store timestamps in UTC and display Brussels time.
- AC: restart/DST do not duplicate successful daily backups; missed days trigger one
  catch-up after DB health, not a backlog of dumps; the same scheduled backup is not
  executed twice. Define operational as DB healthy and the normal API/worker running;
  recheck before starting. Failure remains visible until recovery, without crashing
  the worker. While the application is off no backup runs; document this limitation.
- Automated: injected-clock scheduler tests (both DST changes, startup before/after
  18:00, multi-day absence, unhealthy DB, API/worker unavailable, restart, failed retry,
  concurrency and crash between publication/state write),
  synthetic worker integration, status API/UI tests; ensure no added MT5/AI calls.
- Owner: leave normal app running across 18:00 Brussels, inspect backup success/status;
  next startup confirms catch-up. Failure/recovery exercised in isolated QA only.
- Dependencies/risks: M7-01; worker single-instance contract, slow disk/dump, laptop
  sleep and reliable operational readiness signal. Schedule/catch-up are PM decisions;
  implementation must reconcile archive/state after crashes without duplicate dumps.

### M7-03 [M] Log rotation and retention — `m7/log-retention`

- Scope: audit existing 5 MB x 5 rotating application logs, make retention predictable
  per process, test rollover and document disk bounds. Preserve AI usage audit history
  and any reader/cost calculations; do not apply generic cleanup to ai_usage.jsonl,
  audio, backups or arbitrary logs. If audit-log growth needs redesign, propose separately.
- AC: API/worker logs remain UTF-8, UTC, readable and bounded; errors stay visible;
  multiple processes do not rotate the same file unsafely; no credentials appear.
- Automated: tiny-threshold temporary-directory rollover, retention and restart tests;
  error/redaction tests and existing usage-log regression.
- Owner: inspect readable recent API/worker logs after restart; forced rollover in QA.
- Dependencies/risks: independent of backup implementation; audit current handlers first;
  Windows file locks and audit loss. May run before or after M7-01/02, one task at a time.

### M7-04 [M] Startup health and dependency checks — `m7/startup-checks`

- Scope: extend existing launcher preflight for supported Python/Node/uv/npm,
  PostgreSQL connectivity, dump availability, writable data/log/backup folders,
  validated config, safe migration path and child readiness. Distinguish fatal
  prerequisites from optional AI/MT5 availability; no network AI check added.
- AC: actionable sanitized errors; foreign port owners never killed; failed startup
  cleans up only its own children. Optional unavailable services retain offline flows.
  Pending dev migrations still require successful pre-migration backup first.
- Automated: mocked missing tools, bad config, unavailable DB, permissions/ports,
  readiness timeout and child failure; isolated startup/stop smoke without real MT5.
- Owner: normal PowerShell repo root: `./start.bat`; inspect «Головна» and existing
  status indicators, then `./stop.bat`; two clean restarts. No secrets shared.
- Dependencies/risks: general preflight can follow its existing launcher dependencies;
  backup-specific readiness requires M7-01/02 contract. Windows/Docker startup delay, accidental
  process cleanup, optional-service checks blocking otherwise usable app.

### M7-05 [M] Performance verification and bounded fixes — `m7/performance`

- Scope: measure warm startup to usable UI (<10 s) and local page/API loads (<300 ms)
  using labelled representative synthetic history. Report cold Docker/dependency-install
  times separately; no rewriting financial logic to meet timings.
- AC: reproducible timings for «Головна», «Журнал», «Дайджести», «Калькулятор»;
  investigate failures and propose small fixes with their own tier before implementation.
- Automated: repeatable timing harness, fixed-size dataset, correctness regression for
  any approved fixes; no flaky timing assertions in ordinary unit tests.
- Owner: confirm usable startup and navigation on laptop; record delays during bug bash.
- Dependencies/risks: M7-04; hardware variance, cold caches and data-volume assumptions.

### M7-06 [S] README installation from zero — `m7/setup-docs`

- Scope: prerequisites/versions, Docker and native PostgreSQL routes, local secret setup
  by owner, dependency install, portable MT5 setup link, start/stop, offline behavior,
  backups/retention and safe recovery instructions. Commands from normal PowerShell in
  repo root; exact Ukrainian UI paths. No destructive command against dev/QA databases.
- AC: follow documented sequence in a fresh isolated checkout/config/database; no hidden
  global setup or existing app collision; clearly separate normal start from test gates.
- Automated: validate commands/paths and isolated install/start smoke; no new dependencies.
- Owner: follow fresh-install checklist on clean environment or isolated setup; confirm
  «Налаштування» → «Рахунки», then «Головна». Secret values entered locally only.
- Dependencies/risks: installation baseline can be drafted earlier; final backup/startup
  instructions require M7-01/02/04, performance claims require M7-05. Network/install availability, Docker vs native
  parity. Report an untested route honestly rather than claim fresh-install PASS.

### M7-07 [L] Security/safety audit and integrated QA — `m7/hardening-qa`

- Scope: required pre-M7 security checklist pass, backup restore drill and regression
  across startup/shutdown, error recovery, paths/redaction, localhost exposure and all
  existing journal/bias/calculator/digest flows. Record findings in M7 report; fixes
  are separate scoped tasks with appropriate tier and tests.
- AC: no unresolved blocking security/data-loss issues; synthetic restore verified;
  full final gates green; real records untouched and QA databases retained.
- Automated: targeted security/guard tests, synthetic end-to-end smoke and full checks.
  Use mocks for AI/Whisper; no new paid calls for hardening QA.
- Owner: review backup/recovery evidence and exact UI checklist before week starts.
- Dependencies/risks: after all M7-01..06 implementation/documentation tasks are complete;
  secrets in diagnostics, accidental target confusion.

### M7-08 [L] One real trading week bug bash and closure

- Scope: five actual trading days of Borys's normal use, dated evidence and issue log.
  No artificial trades or agent account operations. Agree start/end dates after QA;
  low-trade days still count as actual app-use days, holidays do not.
- AC: owner signs off all five days; all found defects triaged and fixed/retested or
  explicitly deferred by PM; no unexplained missing/changed trades; final M7 report,
  commit range, verification and remaining limits submitted for PM acceptance.
- Automated: regression test per actionable defect, targeted checks during fixes and
  full make check on each final implementation commit before merge.
- Owner daily (one item per line in eventual checklist):
  «Головна» → inspect account sync, today/week limits and backup status.
  «Потрібен опис» → describe a normal closed trade and save using existing flow.
  «Журнал» → verify that day's trades and edits persist after restart.
  «Біас» → save session bias and inspect alignment through normal use.
  «Калькулятор» → verify usual symbol inputs without placing orders.
  «Дайджести» → end-week metrics/review/next bias; AI button only under separately approved budget.
  Record date, click path, expected/actual result, timing and sanitized error details.
- Dependencies/risks: starts only after M7-01 through M7-07 are accepted; requires five
  actual trading days, owner availability and actual trading calendar; no milestone
  acceptance based solely on synthetic tests. PM decides if a major fix requires
  extending/repeating affected owner checks.

## PM gate

The entire plan is accepted. Schedule (18:00 Europe/Brussels),
one startup catch-up after DB health, duplicate prevention, retention counts,
manual/pre-migration protection, Ukrainian status and isolated restore are binding
PM decisions reflected above. Implement M7-01 only; stop for PM acceptance before M7-02.

Final PM decisions:
1. Weekly/monthly representatives use existing verified daily dumps: latest successful
   archive in each Brussels ISO week/calendar month; retain the union without duplicate files.
2. Performance measurement uses warm operational startup (<10 s) and
   representative local page/API loads (<300 ms), with cold installation/Docker
   startup reported separately. Use reproducible synthetic data and document methodology
   and hardware context. No remaining product decisions block M7-01.

Implementation order: M7-01 before M7-02; M7-03..06 follow their actual dependencies
as specified, sequentially under the sole-engineer rule; M7-07 follows implementation;
M7-08 follows acceptance of M7-01..07 and lasts five actual trading days.
M7-02..08 remain unauthorized until their PM gates. No paid AI calls, real-data destructive
operations, QA deletion or push. No scheduler installation in M7-01.

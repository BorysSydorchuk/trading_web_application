# M4 live check - PM approved with deferred checks

PM approval received 2026-11-07: M4 approved; M5 authorized. Owner-reported results below do not imply unperformed checks passed. M4-09 offline evidence remains separate.

## Safe start

Prerequisite: an existing local PostgreSQL database named exactly
`trading_journal_qa_m4`, with the M4 QA fixture account/trades prepared by the
orchestrator. The launcher does not create, reset or delete a database. Do not
substitute the development database or the retained M3 QA database. A missing QA
database must be created separately by the designated runner, without resetting any
existing database; migrations run through the normal launcher.

Stop the normal application with `stop.bat` first. M4 QA uses the same ports and
process run file as `start.bat`; starting it can stop another launcher from this
checkout. Do not run both applications concurrently.

```powershell
Set-Location "D:\Trading Scripts\WEB_application"
python scripts\qa_live_check_m4.py
```

Optional: `--no-browser`, `--base-dir <outside-repository-folder>`,
`--database-url <existing-local-M4-QA-URL>`. Do not paste a URL containing credentials
into a report. Only postgresql+psycopg:// URLs on localhost/127.0.0.1/::1 with the exact QA database
name is accepted; URL query parameters and fragments are refused.

The script copies `config/` unchanged to `%TEMP%\tj-qa-m4\config`, keeps uploaded
files in `%TEMP%\tj-qa-m4\data`, and puts logs in `%TEMP%\tj-qa-m4\logs`. Only its
marked config copy is replaced on another start. Do not edit UTF-8 files with
PowerShell 5.1 Get-Content/Set-Content. Stop with Ctrl+C or `stop.bat`; retain the QA
database and audio until the owner closes the open checks. No cleanup/drop is authorized.

**This launcher disables AI**, including automatic key checks and warm-up, and uses
fixture MT5 only. The AI unavailable chip is expected. Manual entry, saving, alignment
and reminders work. “Заповнити з тексту” should show the configured-key error; it
cannot demonstrate live extraction quality. Voice uploads still start local Whisper:
do not upload audio until the owner is ready to spend the bounded voice runs.

## Owner checklist

Mark each row ✅ / ❌ with actual date/time, brief observation and screenshot if useful.
Owner/PM update (2026-11-07): rows 1-8 PASSED; rows 9-10 deferred to Monday 2026-11-09, 12:30-16:00 Europe/Brussels; optional row 11 microphone/Whisper SKIPPED; row 12 final review DEFERRED. Separate live-AI evaluation remains pending explicit owner authorization. These follow-ups do not block M5. Preserved fixture trades: EURUSD position 2000101 (trade ID 1); GBPUSD
position 2000201 (trade ID 2). Seeded note IDs: pre_london 1, pre_ny 2, weekly 3,
monthly 4. The daily/weekly date is 2026-10-19; monthly is 2026-10-01.

| # | Do | Expected |
|---|---|---|
| 1 | Start QA; inspect Головна, Біас and Журнал | Ukrainian labels readable; fixture trades appear; expected AI unavailable indicator; no real MT5 connection |
| 2 | Біас: create or open **pre_london, 2026-10-19**; EURUSD bullish; save and reload | Note and symbol entry persist; an existing period opens rather than creating a duplicate |
| 3 | Create or open **pre_ny, 2026-10-19**; GBPUSD bearish; save and reload | Second daily kind persists separately from pre_london |
| 4 | Create or open **weekly, 2026-10-19**, EURUSD bearish and GBPUSD bearish; save | Weekly date normalized to Monday; both entries persist |
| 5 | Журнал: inspect EURUSD buy **position 2000101**, opened 2026-10-19 09:30 Brussels; enable weekly/monthly columns in column settings | Daily aligned; weekly counter; monthly neutral_bias (seeded monthly directions are neutral) |
| 6 | Open that trade → Описати; inspect daily/weekly/monthly values and follow each available bias-note link | Values match Journal; links open the note for the trade period, not today. No link for no_bias |
| 7 | Inspect GBPUSD sell **position 2000201**, opened 2026-10-19 14:05 Brussels | Daily aligned from pre_ny; weekly aligned; monthly neutral_bias |
| 8 | Change weekly EURUSD to bullish, save, revisit trade; then restore bearish | Weekly becomes aligned then counter; daily stays aligned; a manual daily override, if present, remains effective |
| 9 | On a weekday **12:30 ≤ Brussels time < 16:00**, with no pre_ny note for today, inspect Головна and sidebar | Missing pre_ny reminder and badge appear; “Записати біас” opens pre_ny with the server's current Brussels date. Browser timezone alone does not change the server clock |
| 10 | Save today's pre_ny manually with a symbol and direction, return home and wait up to 60 s | Reminder and badge disappear after refresh; note remains after reload. Do not delete an existing note just to force this check |
| 11 | Optional voice check, **at most 3 Whisper transcriptions total**: record/upload one bias note with named symbols and mixed UA/RU/EN trading terms; edit transcript and save manually | Progress, replay and editable normalized transcript work; text and entries persist. Record actual elapsed time and terms. AI filling is unavailable in this offline launcher |
| 12 | Review failures and remaining live checks with Borys | No automated result is counted as visual/microphone/real-model acceptance; M4-10 remains pending until owner confirmation |

If the reminder window is unavailable, leave rows 9–10 pending. Do not change the OS
clock or production rules to manufacture live evidence. The automated API boundary
check uses an injected clock and is reported as such.

Live AI evaluation is a separate owner-authorized run with its own cost/call record.
Do not enable a key in this launcher or silently reuse the two historical M4-06 calls
as new M4-09 evidence. Include the two M4-02 setup-context texts (“Сетап H4, H1 Flow”
and “…, але H1 проти H4”) in that later live evaluation. Inherited M3 mic checks and
QM/BOS/SMT/symbol recognition remain open unless Borys supplies their results.

## M4-09 offline evidence

- Guard tests: `backend/tests/test_qa_live_check_m4.py` exercise local exact DB targeting,
  rejection before filesystem/process changes, offline child environment, unchanged
  config bytes, retained audio and foreign-folder refusal. RED: designated runner
  reported 18 expected missing-launcher errors in 1.58 s before implementation.
  GREEN: designated runner reported 20 passed in 0.27 s; strict new-script mypy passed. Full make check passed on 2026-11-06: 1794 backend passed, 1 intentional real-Whisper skip; 337 frontend passed; all lint/type checks passed. Separate strict launcher mypy passed.
- Existing `backend/tests/fixtures/extraction_bias/` contains 11 simulated model-output
  fixtures, replayed through the extraction service by
  `tests/services/test_bias_extraction_fixtures.py`. Covers UA/RU/EN, aliases, confidence,
  ambiguous/missing values, questions and unmentioned symbols. No live API call.
- Existing API/domain/service cases exercise both daily kinds and weekly/monthly notes,
  alignment recomputation, pre_ny fallback, overrides, server Brussels/DST boundaries,
  and reminder windows. Tests are supporting evidence; they are not owner browser AC.
- Designated runner prepared a **new** local `trading_journal_qa_m4`, migrated it,
  and seeded 7 basic_week trades through the real sync service, account M4 QA fixture.
  No existing database was reset. Real API handlers/TestClient with PostgreSQL created
  both daily notes, weekly and monthly notes with the IDs above. Journal and trade
  detail agreed: EURUSD aligned/counter/neutral_bias; GBPUSD
  aligned/aligned/neutral_bias. PUT London bearish changed EURUSD daily to counter;
  restored bullish changed it back. Entry 1 was manually marked correct.
- Runner reminder evidence uses an **injected server clock** on 2026-10-19 Brussels:
  12:29 no pre_ny reminder, 12:30 reminder, creating pre_ny cleared it. This is real
  handler/DB evidence with controlled time, not browser evidence or natural wall time.
- Runner evidence: `logs/m4-qa-evidence.json`; reproduction:
  `logs/m4_qa_evidence.py` (refuses already seeded data; **do not rerun** against the
  preserved database). The seed script was not repeated during recovery.
- At M4-09 completion, live AI calls and Whisper runs were both **0** and browser checks
  were pending. The 2026-11-07 owner/PM update above now records rows 1-8 passed,
  rows 9-10 and 12 deferred, and optional microphone row 11 skipped.

- Actual launcher smoke on 2026-11-06 passed after reboot freed the app ports: preserved DB counts 7 trades / 4 notes, no queued audio; config validation, migration, API/fixture worker/Vite startup succeeded. HTTP health and frontend returned 200; AI state not_configured; trade 1 alignment and note IDs matched the seed. Controlled stop succeeded. No browser rendering or voice/live-model check was performed.

- Independent Sol code-reviewer and python-reviewer both APPROVE, with no substantive findings. M4-09 offline QA is complete; owner checklist status is superseded by the 2026-11-07 PM update above.

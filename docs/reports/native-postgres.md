# Native PostgreSQL 16 instead of Docker (tier L, owner YES 2026-11-20)

Branch `infra/native-postgres`. Owner guide: `docs/native-postgres.md`.

## What was done

- **New server:** native Windows service «postgresql-x64-16».
  - PostgreSQL 16, EDB installer via winget, without pgAdmin or StackBuilder.
  - Listens on 127.0.0.1 and ::1, port 5433 only (checked with netstat).
  - Starts automatically with Windows.
- **Role and databases:**
  - Role `journal` (LOGIN, CREATEDB); its password is sent as a SCRAM verifier, so no plaintext reaches the server log.
  - Databases `trading_journal` and `trading_journal_test`: UTF-8, ICU en-US collation, Cyrillic lower/ILIKE check passed.
- **Passwords:** all live only in `.env` and were written by the owner's own runs of `scripts/native_pg.py`. The superuser password was changed after the install, because the installer log in %TEMP% may hold the first one.
- **Code:**
  - `pg_dump` / `pg_restore` are found in `%PROGRAMFILES%\PostgreSQL\16\bin` (`app/system/pg_tools.py`), with no PATH change.
  - start.bat, the tray and autostart (`scripts/dev.py`) start the native service if it is stopped. They fall back to Docker only when the database URL uses the Docker port or the native service does not exist.
  - `make check` no longer starts Docker.
- **Fallback:** Docker stays available. The `pgdata` volume was not touched.

## Copy check (owner run, 2026-11-20 15:50 UTC)

- **Backup first:** a checked dump of the Docker database, `backups/pre-native-20261120T154957Z.dump` (`pg_restore --list` OK).
- **Result:** all **17 tables** have identical row counts and identical md5 checksums (UTC, ISO dates, `COLLATE "C"` ordering), and the alembic revision matches (`d3b9f1a7c2e4`).

| Table | Rows | | Table | Rows |
|---|---|---|---|---|
| accounts | 3 | | journal_field_requirements | 18 |
| alembic_version | 1 | | journal_requirements_state | 1 |
| audio_notes | 15 | | rule_violations | 11 |
| bias_entries | 24 | | symbol_specs | 12 |
| bias_notes | 6 | | sync_log | 2992 |
| calculator_margin_requests | 10 | | trade_exit_deals | 29 |
| chart_links | 104 | | trade_stats_exclusions | 3 |
| digests | 5 | | trades | 30 |
| fx_rates | 3 | | | |

## Checks after the switch

- **Gate on the native server:** `make check` (2 workers) passed with 4026 backend / 1 skipped and 719 frontend. The final run on 358b144 passed with 4034 backend / 1 skipped and 719 frontend. The first backend run took 5 min 42 s, against about 12 min on Docker.
- **App:** started in 4.7 s; database latency 1 ms.
- **Sync:** both accounts OK.
- **«Головна»:** open position and limits shown.
- **«Журнал»:** 30 trades.
- **November digest:** 1 457.57 / 1 443.62, as before.
- **Backups:** the worker made the first backup of the native database with native `pg_dump` (state ok).

## Memory

| | Before (Docker serving the DB) | After |
|---|---|---|
| Docker vmmemWSL | 954 MB | 402 MB while Docker is still open but idle; 0 after «Quit Docker Desktop» |
| Native postgres (11 processes) | — | about 94 MB private (247 MB working set incl. shared memory) |

## Reviews

- **python-reviewer:** CHANGES REQUESTED (1 HIGH: `copy --replace` after the switch; 6 MEDIUM), then fixed and APPROVE.
- **code-reviewer:** APPROVE. The README now makes native the default, and the launcher falls back to Docker only when the service is missing.

## How to switch back to Docker

1. `stop.bat`
2. `python -m uv run --project backend python scripts/native_pg.py switch-back`
3. Start Docker Desktop and wait for «Engine running».
4. `start.bat`

Data written to the native database after the switch is not in Docker. Copying it back would be a separate task.

## Not verified / notes

- The EDB installer flags worked on this machine. They are not documented anywhere else in the repo.
- If an older `pg_dump` is on PATH, it is used before the native 16 one. startup_check then reports it clearly (README troubleshooting).

# Recipes must work in both cmd.exe and sh (GNU make on Windows may use either).
.PHONY: install dev stop shortcuts db-ensure db-up migrate check lint typecheck test lint-backend lint-frontend typecheck-backend typecheck-frontend test-backend test-frontend e2e trade-check ai-eval whisper-bench

install:
	cd backend && uv sync
	cd frontend && npm install

dev:
	python scripts/dev.py

# Stop a running app (previous `make dev` / start.bat), like stop.bat.
stop:
	python scripts/dev.py --stop

# db-ensure: make sure PostgreSQL is up by DB_MODE (native: service postgresql-x64-16 on 5433,
# never Docker; docker: the compose db) and apply migrations (pg_dump backup first).
# M8-12: desktop shortcuts «Старт»/«Стоп» + autostart at login (NO_AUTOSTART=1 to turn it off)
NO_AUTOSTART ?=
shortcuts:
	uv run --project backend python scripts/install_shortcuts.py $(if $(NO_AUTOSTART),--no-autostart)

db-ensure:
	python scripts/dev.py --ensure-db

# DB_MODE=docker only (docs/native-postgres.md «Як повернутися на Docker»). Never a prerequisite:
# in DB_MODE=native no make target calls docker (db-ensure/dev go through scripts/dev.py).
db-up:
	docker compose up -d --wait db

migrate:
	cd backend && uv run python -m app.tools.migrate

# Owner rule 2026-11-24 (this laptop): free-RAM check first (>= 3 GB, re-checked up to
# 10 min, then a report instead of a start), then 2 pytest and 2 vitest workers.
check: gate-ram lint typecheck test

gate-ram:
	cd backend && uv run python ../scripts/gate_ram_check.py

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . ../scripts
	cd backend && uv run ruff format --check . ../scripts

lint-frontend:
	cd frontend && npm run lint

typecheck: typecheck-backend typecheck-frontend

typecheck-backend:
	cd backend && uv run mypy
	cd backend && uv run mypy ../scripts/dev.py ../scripts/qa_live_check.py ../scripts/tray.py ../scripts/install_shortcuts.py ../scripts/native_pg.py ../scripts/native_pg_env.py ../scripts/native_pg_compare.py ../scripts/native_pg_diff.py ../scripts/gate_ram_check.py

typecheck-frontend:
	cd frontend && npm run typecheck

test: test-backend test-frontend

# Tests build their own schema on the test DB(s); only Postgres must be up (never migrates the
# dev DB). -n auto: pytest-xdist, one test database per worker (tests/conftest.py).
# Default 2 + 2 workers at all hours (owner rule 2026-11-24); override per run if ever needed.
PYTEST_WORKERS ?= 2
VITEST_WORKERS ?= 2
# No Docker prerequisite since the native PostgreSQL move (2026-11-20): the native service starts
# with Windows; on the Docker fallback run `make db-up` first. An unreachable DB fails visibly.
test-backend:
	cd backend && uv run pytest -n $(PYTEST_WORKERS)

test-frontend:
	cd frontend && npm test$(if $(VITEST_WORKERS), -- --maxWorkers=$(VITEST_WORKERS))

# Browser layout regressions (Playwright, installed Chrome, mocked API; not part of check): make e2e
e2e:
	cd frontend && npm run e2e

# Compare the last N closed trades with MT5 (read-only): make trade-check ACCOUNT="FN P1" N=5
# Optional: OUT=docs/reports/M1_trade_check.md, SOURCE=fixture:<path> (default: MT5_SOURCE / real).
ACCOUNT ?=
N ?= 5
trade-check:
	uv run --project backend python -m app.tools.trade_check --account "$(ACCOUNT)" --last $(N) $(if $(OUT),--out "$(OUT)") $(if $(SOURCE),--source "$(SOURCE)")

# Live AI extraction eval on backend/tests/fixtures/extraction (real API, costs money; needs
# ANTHROPIC_API_KEY): make ai-eval [AI_MODEL=claude-opus-5-5] [AI_EFFORT=low|medium|high]
AI_MODEL ?=
AI_EFFORT ?=
ai-eval:
	uv run --project backend python -m app.tools.ai_eval $(if $(AI_MODEL),--model "$(AI_MODEL)") $(if $(AI_EFFORT),--effort "$(AI_EFFORT)")

# Time local faster-whisper on audio files (QA for M3; downloads the model on first use):
# make whisper-bench FILES="note30s.webm note2min.webm" [WHISPER_MODEL=base]
#   [BENCH_ARGS="--preset old --beam-size 1 --show-text"]   (see --help for all flags)
# WHISPER_* variables given on the make command line (e.g. WHISPER_VAD_FILTER=false) reach the
# tool through the environment and override .env, like in the worker.
FILES ?=
WHISPER_MODEL ?=
BENCH_ARGS ?=
whisper-bench:
	uv run --project backend python -m app.tools.transcribe_bench $(FILES) $(if $(WHISPER_MODEL),--model "$(WHISPER_MODEL)") $(BENCH_ARGS)

# Recipes must work in both cmd.exe and sh (GNU make on Windows may use either).
.PHONY: install dev stop db-ensure db-up migrate check lint typecheck test lint-backend lint-frontend typecheck-backend typecheck-frontend test-backend test-frontend trade-check ai-eval whisper-bench

install:
	cd backend && uv sync
	cd frontend && npm install

dev:
	python scripts/dev.py

# Stop a running app (previous `make dev` / start.bat), like stop.bat.
stop:
	python scripts/dev.py --stop

# Start PostgreSQL if needed (Docker) and apply migrations; no-op when already up.
db-ensure:
	python scripts/dev.py --ensure-db

db-up:
	docker compose up -d --wait db

migrate:
	cd backend && uv run python -m app.tools.migrate

check: lint typecheck test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . ../scripts
	cd backend && uv run ruff format --check . ../scripts

lint-frontend:
	cd frontend && npm run lint

typecheck: typecheck-backend typecheck-frontend

typecheck-backend:
	cd backend && uv run mypy
	cd backend && uv run mypy ../scripts/dev.py ../scripts/qa_live_check.py

typecheck-frontend:
	cd frontend && npm run typecheck

test: test-backend test-frontend

# Tests build their own schema on the test DB(s); only Postgres must be up (never migrates the
# dev DB). -n auto: pytest-xdist, one test database per worker (tests/conftest.py).
test-backend: db-up
	cd backend && uv run pytest -n auto

test-frontend:
	cd frontend && npm test

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

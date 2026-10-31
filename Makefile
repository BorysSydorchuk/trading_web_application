# Recipes must work in both cmd.exe and sh (GNU make on Windows may use either).
.PHONY: install dev db-ensure db-up migrate check lint typecheck test lint-backend lint-frontend typecheck-backend typecheck-frontend

install:
	cd backend && uv sync
	cd frontend && npm install

dev:
	python scripts/dev.py

# Start PostgreSQL if needed (Docker) and apply migrations; no-op when already up.
db-ensure:
	python scripts/dev.py --ensure-db

db-up:
	docker compose up -d --wait db

migrate:
	cd backend && uv run alembic upgrade head

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
	cd backend && uv run mypy ../scripts/dev.py

typecheck-frontend:
	cd frontend && npm run typecheck

test: db-ensure
	cd backend && uv run pytest

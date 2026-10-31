# Recipes must work in both cmd.exe and sh (GNU make on Windows may use either).
.PHONY: install dev db-up migrate check lint typecheck test lint-backend lint-frontend typecheck-backend typecheck-frontend

install:
	cd backend && uv sync
	cd frontend && npm install

dev:
	python scripts/dev.py

db-up:
	docker compose up -d --wait db

migrate:
	cd backend && uv run alembic upgrade head

check: lint typecheck test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .

lint-frontend:
	cd frontend && npm run lint

typecheck: typecheck-backend typecheck-frontend

typecheck-backend:
	cd backend && uv run mypy

typecheck-frontend:
	cd frontend && npm run typecheck

test:
	cd backend && uv run pytest

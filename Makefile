.PHONY: install dev lint format typecheck test cov audit check migrate revision up down image scan admin fullstack google-client-id

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --port 8080

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy app tests migrations

test:
	uv run pytest

cov:
	uv run pytest --cov --cov-report=term --cov-report=xml --cov-fail-under=80

audit:
	uv run pip-audit --strict

check: lint typecheck test

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

up:
	docker compose up -d --build

down:
	docker compose --profile fullstack down

fullstack:
	docker compose --profile fullstack up -d --build fullstack

google-client-id:
	./scripts/google-client-id.sh $(project)

image:
	docker build -t sgsai-backend-api:local .

scan: image
	trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 sgsai-backend-api:local

admin:
	uv run python -m app.cli create-admin --email "$(email)"

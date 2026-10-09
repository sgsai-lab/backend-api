.PHONY: install dev lint format typecheck test check migrate revision up down image scan

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

check: lint typecheck test

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

up:
	docker compose up -d --build

down:
	docker compose down

image:
	docker build -t sgsai-backend-api:local .

scan: image
	trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 sgsai-backend-api:local

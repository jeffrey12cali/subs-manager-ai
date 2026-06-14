.PHONY: up down logs build sh-api sh-worker sh-web migrate revision fmt lint test \
        web-install web-dev api-dev sync test-local lint-local

# --- docker compose ---

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

sh-api:
	docker compose exec api bash

sh-worker:
	docker compose exec worker bash

sh-web:
	docker compose exec web sh

migrate:
	docker compose exec api uv run alembic upgrade head

revision:
	docker compose exec api uv run alembic revision --autogenerate -m "$(m)"

fmt:
	docker compose exec api uv run ruff format app
	docker compose exec api uv run ruff check --fix app

lint:
	docker compose exec api uv run ruff check app

test:
	docker compose exec api uv run pytest -q

# --- local (uv outside docker) ---

sync:
	cd api && uv sync --extra dev

test-local: sync
	cd api && uv run pytest -q

lint-local: sync
	cd api && uv run ruff check app

api-dev: sync
	cd api && uv run uvicorn app.main:app --reload

# --- web ---

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

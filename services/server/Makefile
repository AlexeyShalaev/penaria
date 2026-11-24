.PHONY: install fmt check test test-unit test-integration run-api migrate migration openapi

# The development stack from the repository root (`make dev-up`); override any of them.
export PENARIA_DATABASE__CONNECTION__HOST ?= localhost
export PENARIA_DATABASE__CONNECTION__PORT ?= 55432
export PENARIA_DATABASE__CONNECTION__USER ?= penaria
export PENARIA_DATABASE__CONNECTION__PASSWORD ?= penaria
export PENARIA_DATABASE__CONNECTION__DATABASE ?= penaria
# The integration tests use a database of their own on the same server (no PENARIA_ prefix:
# the processes reject unknown PENARIA_ variables).
export TEST_DATABASE_URL ?= postgresql+asyncpg://penaria:penaria@localhost:55432/penaria_test

install:  ## Install dependencies
	uv sync --frozen

fmt:  ## Format and fix lint findings
	uv run ruff format
	uv run ruff check --fix

check:  ## Lint, types and import rules, read-only (same steps as CI)
	uv run ruff check
	uv run ruff format --check
	uv run mypy
	uv run lint-imports

test:  ## All tests with coverage; the integration tests need `make dev-up`
	uv run pytest --cov --cov-report=term --cov-report=xml

test-unit:  ## Unit tests only, no database
	uv run pytest -m unit

test-integration:  ## Integration tests only (database)
	uv run pytest -m integration

run-api:  ## Run the API on :8000 against the development database
	uv run python -m penaria.apps.api

migrate:  ## Apply the migrations to the development database
	uv run python -m penaria.apps.migrate upgrade

migration:  ## Write a migration from the models: make migration m="what changes"
	uv run python -m penaria.apps.migrate revision -m "$(m)"

openapi:  ## Export the OpenAPI document to openapi.json (the web app's API client is generated from it)
	uv run python -m penaria.apps.api.openapi > openapi.json

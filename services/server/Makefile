.PHONY: install fmt check test test-unit test-integration run-api run-worker migrate migration openapi

# The development stack from the repository root (`make dev-up`); override any of them.
export PENARIA_DATABASE__CONNECTION__HOST ?= localhost
export PENARIA_DATABASE__CONNECTION__PORT ?= 55432
export PENARIA_DATABASE__CONNECTION__USER ?= penaria
export PENARIA_DATABASE__CONNECTION__PASSWORD ?= penaria
export PENARIA_DATABASE__CONNECTION__DATABASE ?= penaria
# The integration tests use a database of their own on the same server (no PENARIA_ prefix:
# the processes reject unknown PENARIA_ variables).
export TEST_DATABASE_URL ?= postgresql+asyncpg://penaria:penaria@localhost:55432/penaria_test
# The development storage (SILO), for the tests that keep files in buckets of their own.
export TEST_S3_URL ?= http://penaria:penaria-dev@127.0.0.1:59000

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

# The development storage and its bucket (`make dev-up` makes it), for the processes that keep files.
run-api run-worker migrate: export PENARIA_S3__ENDPOINT ?= http://127.0.0.1:59000
run-api run-worker migrate: export PENARIA_S3__BUCKET ?= penaria
run-api run-worker migrate: export PENARIA_S3__ACCESS_KEY_ID ?= penaria
run-api run-worker migrate: export PENARIA_S3__SECRET_ACCESS_KEY ?= penaria-dev

# People open the web app's dev server (make -C ../web dev), which proxies the API; the key is
# public, like every development credential here.
run-api: export PENARIA_PUBLIC_URL ?= http://localhost:5173
run-api: export PENARIA_SECRET_KEY ?= development-only-secret-key-never-use-it-at-home
run-api:  ## Run the API on :8000 against the development database; its log prints the setup token
	uv run python -m penaria.apps.api

run-worker:  ## Run the worker, which cleans and previews uploaded files, against the development stack
	uv run python -m penaria.apps.worker

migrate:  ## Apply the migrations to the development database
	uv run python -m penaria.apps.migrate upgrade

migration:  ## Write a migration from the models: make migration m="what changes"
	uv run python -m penaria.apps.migrate revision -m "$(m)"

openapi:  ## Export the OpenAPI document to openapi.json (the web app's API client is generated from it)
	uv run python -m penaria.apps.api.openapi > openapi.json

.PHONY: install fmt check test test-unit run-api

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

test:  ## All tests with coverage
	uv run pytest --cov --cov-report=term --cov-report=xml

test-unit:  ## Unit tests only
	uv run pytest -m unit

run-api:  ## Run the API on :8000
	uv run python -m penaria.apps.api

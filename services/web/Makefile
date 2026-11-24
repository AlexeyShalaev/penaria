.PHONY: install fmt check test build dev api

install:  ## Install dependencies
	pnpm install --frozen-lockfile

fmt:  ## Format the code
	pnpm format

check:  ## Lint, formatting, types and a fresh API client, read-only (same steps as CI)
	pnpm lint
	pnpm format:check
	pnpm typecheck
	pnpm api:check

test:  ## Tests with coverage
	pnpm test:coverage

build:  ## Production build into dist/
	pnpm build

dev:  ## Dev server on :5173, /api and /system proxied to the server on :8000
	pnpm dev

api:  ## Generate the API client types from the server's OpenAPI document (make -C ../server openapi first)
	pnpm api:generate

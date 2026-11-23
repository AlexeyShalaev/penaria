.PHONY: install fmt check test build dev

install:  ## Install dependencies
	pnpm install --frozen-lockfile

fmt:  ## Format the code
	pnpm format

check:  ## Lint, formatting and types, read-only (same steps as CI)
	pnpm lint
	pnpm format:check
	pnpm typecheck

test:  ## Tests with coverage
	pnpm test:coverage

build:  ## Production build into dist/
	pnpm build

dev:  ## Dev server on :5173, /api and /system proxied to the server on :8000
	pnpm dev

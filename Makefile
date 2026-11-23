# The entry point for every project command; each service has its own Makefile with the details.
SERVICES := server web

.DEFAULT_GOAL := help
.PHONY: help install fmt check test hooks hadolint change changelog

help:  ## Show the commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

install:  ## Install the dependencies of every service
	@for s in $(SERVICES); do $(MAKE) -C services/$$s install || exit 1; done

fmt:  ## Format every service
	@for s in $(SERVICES); do $(MAKE) -C services/$$s fmt || exit 1; done

check:  ## Lint and type-check every service and the scripts, read-only (the same steps as CI)
	@for s in $(SERVICES); do $(MAKE) -C services/$$s check || exit 1; done
	uvx ruff check scripts
	uvx ruff format --check scripts
	python3 scripts/release/notes.py check

test:  ## Test every service and the scripts
	@for s in $(SERVICES); do $(MAKE) -C services/$$s test || exit 1; done
	uv run --no-project --with pytest pytest scripts -q

change:  ## Add a release note fragment: make change slug=<what-changed> type=<added|fixed|...>
	python3 scripts/release/notes.py new "$(slug)" --type "$(type)"

changelog:  ## Regenerate CHANGELOG.md from release-notes.json
	python3 scripts/release/notes.py changelog

hooks:  ## Install the git hooks (pre-commit and commit-msg)
	uvx pre-commit install

hadolint:  ## Lint every Dockerfile with .hadolint.yaml, as CI does
	@for f in services/*/Dockerfile; do echo "$$f"; docker run --rm -i -v "$(CURDIR)/.hadolint.yaml:/.hadolint.yaml:ro" hadolint/hadolint hadolint --config /.hadolint.yaml - < $$f || exit 1; done

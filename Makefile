# The entry point for every project command; each service has its own Makefile with the details.
SERVICES := server web

.DEFAULT_GOAL := help
.PHONY: help install fmt check test hooks hadolint

help:  ## Show the commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

install:  ## Install the dependencies of every service
	@for s in $(SERVICES); do $(MAKE) -C services/$$s install || exit 1; done

fmt:  ## Format every service
	@for s in $(SERVICES); do $(MAKE) -C services/$$s fmt || exit 1; done

check:  ## Lint and type-check every service, read-only (the same steps as CI)
	@for s in $(SERVICES); do $(MAKE) -C services/$$s check || exit 1; done

test:  ## Test every service
	@for s in $(SERVICES); do $(MAKE) -C services/$$s test || exit 1; done

hooks:  ## Install the git hooks (pre-commit and commit-msg)
	uvx pre-commit install

hadolint:  ## Lint every Dockerfile with .hadolint.yaml, as CI does
	@for f in services/*/Dockerfile; do echo "$$f"; docker run --rm -i -v "$(CURDIR)/.hadolint.yaml:/.hadolint.yaml:ro" hadolint/hadolint hadolint --config /.hadolint.yaml - < $$f || exit 1; done

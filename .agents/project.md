# Project profile

## About

- What this repository is, in one sentence: Penaria, an open-source home system: a registry of homes, rooms and things with photos and documents, AI search, a calendar of recurring household tasks, family and guest access, and smart home control through pluggable modules (KNX first).
- Who uses it: households that run their own instance (self-hosted OSS); module authors who add integrations.
- Language, version and main frameworks: `services/server` is Python 3.15 (servicewright, FastAPI, dishka, Pydantic v2; later async SQLAlchemy 2, Alembic and other bedrock-python libraries), managed with uv; `services/web` is TypeScript 6 and React 19 with Vite, managed with pnpm.
- Where the documentation lives: `docs/`.

## Commands

From the root for every service, or from `services/<service>/` for one (its `Makefile` lists the details).

| Task | Command |
|---|---|
| Install dependencies | `make install` |
| Format | `make fmt` |
| Lint and type-check (the same steps as CI) | `make check` |
| Test | `make test` |
| Git hooks | `make hooks` |
| Run the API locally (:8000) | `make -C services/server run-api` |
| Run the web app locally (:5173) | `make -C services/web dev` |
| Stop the local run | Ctrl+C |

## Conventions

- Default branch: `master`. Changes reach it only through pull requests.
- Issue tracker: GitHub Issues of this repository; refer to an issue as `#123`.
- Branch names: `<type>/<short-description>`, such as `feat/registry-entities`.
- Worktrees: always in `local/worktrees/<short-description>` (ignored by git), never next to the clone. Remove a worktree once its pull request is merged or the work is dropped. `.agents/skills/worktree/SKILL.md` creates, lists and cleans them up.
- Commit messages: Conventional Commits, `<type>(<scope>): <description>`. Pull requests are squash-merged, so a pull request's title is a Conventional Commit too. No AI attribution lines in commits or pull requests.
- Language of pull request titles and descriptions: English.
- Languages of the docs, of code comments and of notes for agents: English. User-facing strings are never hard-coded: the UI is internationalized from day one, with `en` and `ru` as the primary locales.
- Where operational runbooks live: `docs/` (to be created with the deployment).
- Where specs and design notes go: `docs/design/`. A new area gets a design before code.

## Boundaries

- Paths agents must not edit: applied Alembic migrations, generated API clients (regenerate them from OpenAPI instead).
- Systems and data agents must never touch: real personal data. Never commit floor plans, ETS projects, addresses or inventories of a real home; test fixtures are synthetic or anonymized.

## Notes

Architecture, decided and not to be re-litigated without the author:

- Core first, integrations as modules. KNX and every other integration is a module on top of the core through a contract. If an integration needs a change in the core, the core is missing an extension point.
- Core model: entity (a node in the home tree with a fixed `kind`: property, building, floor, space, container, item, system, device), aspect (schema-validated fields; modules add aspects, not tables), relation (typed edge), event (append-only journal). Every field carries provenance (source, confidence or status, observed_at). Bulk and automatic changes (imports, AI) go through a changeset that a person accepts.
- Modules declare nine extension points in a manifest (aspects, relations, importers, capabilities and actions, time series, events, maintenance templates, AI tools, UI slots) and never touch the database directly.
- Bounded contexts of the core: identity, registry, documents, changes, maintenance, assistant, devices, platform, notifications. They talk only through events and public application ports.
- Smart home control runs through a local hub on each property, with an outbound secure channel to the cloud; the property keeps working offline.
- Infrastructure is supplied by the operator: PostgreSQL 15+ (ltree, pg_trgm), S3-compatible storage, Qdrant, Temporal; Redis only with more than one api replica; an LLM provider is optional. Configuration only through environment variables.
- Delivery: images `all-in-one`, `api`, `worker`, `web`, `migrate`, `hub` (multi-arch, ghcr.io); Docker Compose, Docker Swarm, Kubernetes through our own Helm chart.
- Layout: every deployable is a folder in `services/` with its own dependencies, `Makefile` and `Dockerfile`. `services/server` is one Python package, `penaria`, run as several processes: `apps/<process>` only assembles settings, the DI container and entrypoints (api now; worker, standalone = api + worker in one process, tgbot, cli and the on-site hub as their code lands); `features/{core,support,shared}` hold the product by feature, inside a feature `api -> use_cases -> domain` with `infra` implementing domain's interfaces; `modules/` the home integrations; `integrations/` the adapters to infrastructure; `common/` code with no feature logic. The import rules are contracts in `services/server/pyproject.toml`. `services/web` follows Feature-Sliced Design. Shared code between services (`libs/`) appears when a second consumer needs it; Kubernetes gets one Helm chart with components switched in values.

Open questions: the DI container (Dishka assumed); event delivery without a required Kafka (omni-box ships only a Kafka adapter; plan: our own publisher from the outbox to internal handlers and Temporal signals, Kafka optional for large installs).

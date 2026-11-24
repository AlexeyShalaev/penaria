# Penaria

*Penaria* (Latin): a pantry under the protection of the Penates, the guardians of the home.

Penaria is an open-source home system. It keeps a living registry of your home and lets you control it from the browser.

- **Registry.** Properties, buildings, floors, rooms, containers and things, with photos and documents (receipts, manuals, drawings).
- **Search and assistant.** Ask "where is the vacuum cleaner?" and get the place, the photo and the receipt.
- **Household calendar.** Recurring tasks, from changing filters to checking the boiler.
- **Family and guests.** Shared access for the household, limited access for guests.
- **Smart home control.** Pluggable modules: KNX first, more integrations later.

The interface is internationalized: English and Russian first, other languages later.

> **Status:** early development. The repository is being set up; there is nothing to run yet.

## How it is built

Penaria has a small core and modules on top of it.

- **The core** models a home as a tree of entities with aspects (typed fields), relations and an append-only event journal. Every field records where it came from. Imports and AI suggestions arrive as drafts that a person accepts.
- **Modules** add integrations through declared extension points: new aspects and relations, importers, device capabilities, time series, AI tools and UI slots. They never change the core.
- **A local hub** on each property talks to the devices and keeps the property working offline. It reaches the server over an outbound secure channel.

| Part | Stack |
|---|---|
| Backend | Python, servicewright, FastAPI, Pydantic v2, async SQLAlchemy 2, Alembic; uv |
| Frontend | TypeScript, React, PWA; pnpm; API client generated from OpenAPI |
| Infrastructure (you provide it) | PostgreSQL 15+, S3-compatible storage, Qdrant, Temporal; Redis for more than one API replica; an LLM provider is optional |
| Delivery | Docker images `penaria-server` (every backend process, chosen by the command) and `penaria-web`; Docker Compose, Docker Swarm, Kubernetes with one Helm chart |

## Repository layout

```
services/
  server/    Python backend, one package run as several processes (api now; worker, bot, hub later)
  web/       React PWA
```

Each service has its own dependencies, lock file, `Makefile` and `Dockerfile`. The root `Makefile` runs the same command in every service:

| Task | Command |
|---|---|
| Install | `make install` |
| Format | `make fmt` |
| Lint and type-check (as CI) | `make check` |
| Test (the server's integration tests need `make dev-up`) | `make test` |
| Git hooks | `make hooks` |
| Start PostgreSQL, S3 and Mailpit (a mailbox that catches every email, at http://localhost:58025) for development | `make dev-up` |
| Stop them, keeping or deleting the data | `make dev-down`, `make dev-reset` |

Released images: `ghcr.io/alexeyshalaev/penaria-server` and `ghcr.io/alexeyshalaev/penaria-web`.

## License

[AGPL-3.0](LICENSE).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Coding agents start from [AGENTS.md](AGENTS.md).

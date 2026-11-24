# Penaria server

The backend of Penaria: one Python package, `penaria`, run as several processes.

| Process | Command | What it does |
|---|---|---|
| api | `python -m penaria.apps.api` | REST and WebSocket |
| migrate | `python -m penaria.apps.migrate upgrade` | Applies the database migrations and exits; runs before a new version starts |

More processes join `src/penaria/apps/` as their first code lands: the worker (Temporal, the outbox publisher, event handlers), standalone (api and worker in one process for home installs), the Telegram bot, the CLI and the on-site hub.

## Configuration

Only environment variables, all named `PENARIA_*`; `__` reaches into a section: `PENARIA_SERVER__PORT=8080` sets `server.port`. A `PENARIA_*` variable that names no setting stops the process at startup, so a typo never goes unnoticed. The settings of each process are in `src/penaria/apps/<process>/settings.py`.

The database: `PENARIA_DATABASE__CONNECTION__HOST`, `..._PORT`, `..._USER`, `..._PASSWORD` (required) and `..._DATABASE` (required); the pool under `PENARIA_DATABASE__POOL__*`. PostgreSQL 15 or newer, with the `ltree` and `pg_trgm` extensions available (the first migration creates them).

## Layout

```
src/penaria/
  apps/          one package per process; assembles settings, DI container and entrypoints
  features/      core/ (the registry), support/ (the other contexts), shared/ (shared kernel);
                 inside a feature: api -> use_cases -> domain, infra implements domain's interfaces
  modules/       home integrations (KNX, Yandex, ...) through the core's extension points
  integrations/  adapters to infrastructure and outside services
  migrations/    Alembic migrations of the whole database
  common/        code with no feature logic
```

The dependency rules live in `pyproject.toml` (`[tool.importlinter]`) and are checked by `make check`.

## Commands

| Task | Command |
|---|---|
| Install | `make install` |
| Format | `make fmt` |
| Lint, types, import rules | `make check` |
| Test; the integration tests need `make dev-up` in the repository root | `make test` |
| Unit tests only, no database | `make test-unit` |
| Apply the migrations to the development database | `make migrate` |
| Write a migration from the models | `make migration m="what changes"` |
| Run the API against the development database | `make run-api` |

The Makefile points every command at the development stack (`scripts/dev/compose.yaml`); set the `PENARIA_DATABASE__*` variables, or `TEST_DATABASE_URL` for the tests, to use another server. Migrations run only through the migrate process, never through the bare `alembic` command, and every migration is tested to upgrade, downgrade and upgrade again, and to match the models (`tests/integration/test_migrations.py`).

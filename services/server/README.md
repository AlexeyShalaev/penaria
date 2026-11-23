# Penaria server

The backend of Penaria: one Python package, `penaria`, run as several processes.

| Process | Command | What it does |
|---|---|---|
| api | `python -m penaria.apps.api` | REST and WebSocket |

More processes join `src/penaria/apps/` as their first code lands: the worker (Temporal, the outbox publisher, event handlers), standalone (api and worker in one process for home installs), the Telegram bot, the CLI and the on-site hub.

## Layout

```
src/penaria/
  apps/          one package per process; assembles settings, DI container and entrypoints
  features/      core/ (the registry), support/ (the other contexts), shared/ (shared kernel);
                 inside a feature: api -> use_cases -> domain, infra implements domain's interfaces
  modules/       home integrations (KNX, Yandex, ...) through the core's extension points
  integrations/  adapters to infrastructure and outside services
  common/        code with no feature logic
```

The dependency rules live in `pyproject.toml` (`[tool.importlinter]`) and are checked by `make check`.

## Commands

| Task | Command |
|---|---|
| Install | `make install` |
| Format | `make fmt` |
| Lint, types, import rules | `make check` |
| Test | `make test` |
| Run the API | `make run-api` |

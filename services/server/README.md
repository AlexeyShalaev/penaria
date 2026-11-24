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

The api process also needs these; the migrate process accepts them too, so one environment serves every process of the image:

| Variable | Meaning |
|---|---|
| `PENARIA_PUBLIC_URL` | Required. The address people open, such as `https://home.example.org`: the root of a site, without a path. Requests that change something are refused when the browser says they come from another site (`Origin`), and the session cookie is `Secure` when it is `https`. Its host name is what passkeys belong to |
| `PENARIA_SECRET_KEY` | Required, at least 32 characters, such as the output of `openssl rand -hex 32`. Later versions encrypt stored secrets with it, so keep it and never change it |

Behind a reverse proxy, let the server trust its `X-Forwarded-For`, so that the session list and the sign-in limits see people's addresses rather than the proxy's: `PENARIA_SERVER__UVICORN__FORWARDED_ALLOW_IPS=<the proxy's address>`. Without it everyone signs in from the proxy's address, and five wrong passwords by anyone make everyone wait.

## HTTP API

REST under `/api/v1`; the OpenAPI document is at `/system/openapi.json`, Swagger UI at `/system/docs`. The same document is committed as `openapi.json` (`make openapi` exports it without a database), and the web app generates its API types from it; a unit test fails when the committed file no longer matches the code. So far: setup and signing in (`/setup`, `/sign-in`, `/sign-in/passkey`, `/sign-out`), the signed-in account, its sessions and passkeys (`/me`, `/me/password`, `/me/sessions`, `/me/passkeys`, `/me/reauthenticate`), the account's homes (`/homes`), a home's people (`/homes/{id}/roles`, `/members`, `/grants/{id}`, `:leave`, `/invitations`, `/guest-links`), accepting invitations (`/invitations:preview`, `:accept`, `:accept-new-account`), guest visits (`/guest-sessions`, `/guest`), the home tree (`/homes/{id}/entities`, `/entities/{id}`, with `:move`, `:archive`, `:restore`, `:verify` and `/history`). Errors are `application/problem+json` with a stable `code`; a request without a session answers 401 with the code `unauthenticated`.

## Sign-in and the first start

The web app signs in with a passkey, or with a username and a password, and keeps a session cookie, `penaria_session` (`docs/design/sign-in.md`). Until an account exists, the api process prints a one-time setup token to its log on every start, and the setup screen asks for it before making the first account, the install's admin:

```sh
docker compose logs penaria-server | grep "setup token"   # a Compose install
make run-api                                               # development: the token is in the output
```

Each start before setup prints a new token and the old one stops working; with several api replicas, use the token of the one that started last. An install from before sign-in keeps its data: setup turns its one local user, with its homes, into the new account.

People join a home through invitations: whoever manages the home's people makes a link (`<PENARIA_PUBLIC_URL>/invite/<token>`) with a role, a place and an end of access, and the person accepts it with their account or makes one through it; there is no open sign-up. Guest links (`<PENARIA_PUBLIC_URL>/guest/<token>`) need no account: opening one gives the browser a guest session that sees only guest-visible things and ends when the link expires or is revoked. Both links are shown once, when made: the server keeps only hashes of their tokens. The rules are in `docs/design/sign-in.md`, section 14.

Passkeys belong to the host name of `PENARIA_PUBLIC_URL`: browsers offer them only on `https` with a domain name, or on `localhost`, so an install opened at a plain IP address signs in with passwords only. Changing the host name later makes every passkey unusable (people sign in with their password and add a new one). Adding or removing a passkey needs a sign-in within the last 10 minutes; the web app asks for the password or a passkey again when it is older.

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
| Export the OpenAPI document to `openapi.json` | `make openapi` |

The Makefile points every command at the development stack (`scripts/dev/compose.yaml`); set the `PENARIA_DATABASE__*` variables, or `TEST_DATABASE_URL` for the tests, to use another server. Migrations run only through the migrate process, never through the bare `alembic` command, and every migration is tested to upgrade, downgrade and upgrade again, and to match the models (`tests/integration/test_migrations.py`).

# Penaria server

The backend of Penaria: one Python package, `penaria`, run as several processes.

| Process | Command | What it does |
|---|---|---|
| api | `python -m penaria.apps.api` | REST and WebSocket |
| migrate | `python -m penaria.apps.migrate upgrade` | Applies the database migrations and exits; runs before a new version starts |
| cli | `python -m penaria.apps.cli users reset <username> [--disable-second-factor]` | The operator's tools: prints a one-time password reset link for an account, for an owner who is locked out; can also turn its authenticator app off |

More processes join `src/penaria/apps/` as their first code lands: the worker (Temporal, the outbox publisher, event handlers), standalone (api and worker in one process for home installs), the Telegram bot and the on-site hub.

## Configuration

Only environment variables, all named `PENARIA_*`; `__` reaches into a section: `PENARIA_SERVER__PORT=8080` sets `server.port`. A `PENARIA_*` variable that names no setting stops the process at startup, so a typo never goes unnoticed. The settings of each process are in `src/penaria/apps/<process>/settings.py`.

The database: `PENARIA_DATABASE__CONNECTION__HOST`, `..._PORT`, `..._USER`, `..._PASSWORD` (required) and `..._DATABASE` (required); the pool under `PENARIA_DATABASE__POOL__*`. PostgreSQL 15 or newer, with the `ltree` and `pg_trgm` extensions available (the first migration creates them).

The api process also needs these; the migrate and cli processes accept them too, so one environment serves every process of the image:

| Variable | Meaning |
|---|---|
| `PENARIA_PUBLIC_URL` | Required. The address people open, such as `https://home.example.org`: the root of a site, without a path. Requests that change something are refused when the browser says they come from another site (`Origin`), and the session cookie is `Secure` when it is `https`. Its host name is what passkeys belong to |
| `PENARIA_SECRET_KEY` | Required, at least 32 characters, such as the output of `openssl rand -hex 32`. Stored secrets (the mailbox's password, queued email) are encrypted with a key derived from it: keep it, and back it up apart from the database |
| `PENARIA_RETIRED_SECRET_KEYS` | Optional. Earlier values of `PENARIA_SECRET_KEY`, separated by commas, while you rotate it: what they encrypted still opens, and new secrets use the new key. Save the mailbox's password again in Settings, then drop the old key. With several api replicas, first add the new key here on every replica, and only then make it `PENARIA_SECRET_KEY` |
| `PENARIA_MAIL__HOST`, `..._PORT`, `..._SECURITY` (`starttls`, `tls` or `none`), `..._USERNAME`, `..._PASSWORD`, `..._FROM_ADDRESS`, `..._FROM_NAME` | Optional outgoing email. Usually an install admin connects the mailbox in the web app (Settings); set these to manage it as configuration instead. With `PENARIA_MAIL__HOST` set, every mail setting comes from the environment (`..._FROM_ADDRESS` is then required, and the port defaults to 587, 465 or 25 by the security) and the web app shows them locked |

Behind a reverse proxy, let the server trust its `X-Forwarded-For`, so that the session list and the sign-in limits see people's addresses rather than the proxy's: `PENARIA_SERVER__UVICORN__FORWARDED_ALLOW_IPS=<the proxy's address>`. Without it everyone signs in from the proxy's address, and five wrong passwords by anyone make everyone wait.

## HTTP API

REST under `/api/v1`; the OpenAPI document is at `/system/openapi.json`, Swagger UI at `/system/docs`. The same document is committed as `openapi.json` (`make openapi` exports it without a database), and the web app generates its API types from it; a unit test fails when the committed file no longer matches the code. So far: setup and signing in (`/setup`, `/sign-in`, `/sign-in/second-factor`, `/sign-in/passkey`, `/sign-out`), recovery (`/mail`, `/password-reset:request`, `:preview`, `/password-reset`, `/email-verifications:confirm`), the signed-in account, its email, sessions, passkeys and second factor (`/me`, `/me/email`, `/me/password`, `/me/sessions`, `/me/passkeys`, `/me/second-factor`, `/me/totp`, `:confirm`, `/me/totp/recovery-codes`, `/me/reauthenticate`), the install's settings for its admins (`/install/mail`, `:test`, `/status`, `/messages`), the account's homes (`/homes`), a home's people (`/homes/{id}/roles`, `/members`, `/members/{id}:reset-link`, `/grants/{id}`, `:leave`, `/invitations`, `/guest-links`), accepting invitations (`/invitations:preview`, `:accept`, `:accept-new-account`), guest visits (`/guest-sessions`, `/guest`), the home tree (`/homes/{id}/entities`, `/entities/{id}`, with `:move`, `:archive`, `:restore`, `:verify` and `/history`). Errors are `application/problem+json` with a stable `code`; a request without a session answers 401 with the code `unauthenticated`.

## Sign-in and the first start

The web app signs in with a passkey, or with a username and a password, and keeps a session cookie, `penaria_session` (`docs/design/sign-in.md`). Until an account exists, the api process prints a one-time setup token to its log on every start, and the setup screen asks for it before making the first account, the install's admin:

```sh
docker compose logs penaria-server | grep "setup token"   # a Compose install
make run-api                                               # development: the token is in the output
```

Each start before setup prints a new token and the old one stops working; with several api replicas, use the token of the one that started last. An install from before sign-in keeps its data: setup turns its one local user, with its homes, into the new account.

People join a home through invitations: whoever manages the home's people makes a link (`<PENARIA_PUBLIC_URL>/invite/<token>`) with a role, a place and an end of access, and the person accepts it with their account or makes one through it; there is no open sign-up. Guest links (`<PENARIA_PUBLIC_URL>/guest/<token>`) need no account: opening one gives the browser a guest session that sees only guest-visible things and ends when the link expires or is revoked. Both links are shown once, when made: the server keeps only hashes of their tokens. The rules are in `docs/design/sign-in.md`, section 14.

Passkeys belong to the host name of `PENARIA_PUBLIC_URL`: browsers offer them only on `https` with a domain name, or on `localhost`, so an install opened at a plain IP address signs in with passwords only. Changing the host name later makes every passkey unusable (people sign in with their password and add a new one). Adding or removing a passkey needs a sign-in within the last 10 minutes; the web app asks for the password or a passkey again when it is older.

Two-step sign-in: an account may add an authenticator app (TOTP: six digits, 30 seconds, as Google Authenticator, 1Password and the like make them) on its account page, and then signing in with the password asks for a code from it too; ten single-use recovery codes stand in for the phone when it is lost. Signing in with a passkey asks for no code. The app's secret is stored encrypted with `PENARIA_SECRET_KEY`, so changing that key without keeping the old one in `PENARIA_RETIRED_SECRET_KEYS` leaves only the recovery codes working. Owners of a home and the install's admins who sign in with a password must have an authenticator app or a passkey: until they add one, they are asked for it right after signing in, and handing a home over, changing people's access, making reset links and the install's settings answer `403 second_factor_required` (`docs/design/sign-in.md`, section 16).

## Outgoing email

An install sends email through one mailbox: password reset links, email confirmations, invitations and notices about an account (a changed password, a new passkey, two-step sign-in turned on or off, a recovery code used, recovery codes renewed), in the recipient's language, as text and HTML. Until a mailbox is connected, nothing is sent: reset and invitation links are shown on screen to pass on by hand, and accounts cannot add an email.

Every email is queued in PostgreSQL (`identity_mail`, its text encrypted with `PENARIA_SECRET_KEY`, since links in it open accounts) in the same transaction as the change it is about, and a loop inside every api process sends what is due within a few seconds. A temporary failure (a `4xx` reply, a connection that did not open or broke off) is tried again after 1, 5, 15 and 30 minutes; a permanent one is not. With several api replicas, each email is taken by one of them under a five-minute lease (`SELECT … FOR UPDATE SKIP LOCKED`), so none goes twice and one left by a stopped replica is taken again. Every attempt is a row of the mail log, which Settings shows with a button to send an email again while its link works; the log keeps 30 days, the text of an email only while it can be sent.

In development, `make dev-up` starts Mailpit, which catches every email: connect it in Settings with server `127.0.0.1`, port `51025`, no encryption and any login, and read the email at http://localhost:58025.

## Recovery

Someone who forgot the password asks for a reset link on the sign-in page; it goes to the account's confirmed email and works once, for 30 minutes. The answer is the same for any username or address. Without email, an admin of a home makes a reset link for a member on the People page (24 hours, shown once). An owner who is locked out with nobody to ask gets one from the server:

```sh
docker compose exec penaria-server python -m penaria.apps.cli users reset <username>   # a Compose install
```

It needs the install's environment (the database and `PENARIA_PUBLIC_URL`) and prints the link with when it stops working.

A reset sets a new password and ends every session of the account; its passkeys and its authenticator app keep working, so signing in with the new password still asks for a code. Someone who lost the phone signs in with a recovery code and sets the app up again. Someone who lost the phone and the recovery codes asks the operator, who turns the app off with the reset:

```sh
docker compose exec penaria-server python -m penaria.apps.cli users reset <username> --disable-second-factor
```

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

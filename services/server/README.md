# Penaria server

The backend of Penaria: one Python package, `penaria`, run as several processes.

| Process | Command | What it does |
|---|---|---|
| api | `python -m penaria.apps.api` | REST and WebSocket |
| worker | `python -m penaria.apps.worker` | Cleans and previews uploaded files, empties the trash ("Files and the worker" below) |
| migrate | `python -m penaria.apps.migrate upgrade` | Applies the database migrations, creates the storage's bucket if it is missing, and exits; runs before a new version starts |
| cli | `python -m penaria.apps.cli users reset <username> [--disable-second-factor]` | The operator's tools: prints a one-time password reset link for an account, for an owner who is locked out; can also turn its authenticator app off |

More processes join `src/penaria/apps/` as their first code lands: standalone (api and worker in one process for home installs), the Telegram bot and the on-site hub. Temporal, the outbox publisher and event handlers join the worker when their first code lands.

## Configuration

Only environment variables, all named `PENARIA_*`; `__` reaches into a section: `PENARIA_SERVER__PORT=8080` sets `server.port`. A `PENARIA_*` variable that names no setting stops the process at startup, so a typo never goes unnoticed. The settings of each process are in `src/penaria/apps/<process>/settings.py`.

The database: `PENARIA_DATABASE__CONNECTION__HOST`, `..._PORT`, `..._USER`, `..._PASSWORD` (required) and `..._DATABASE` (required); the pool under `PENARIA_DATABASE__POOL__*`. PostgreSQL 15 or newer, with the `ltree` and `pg_trgm` extensions available (the first migration creates them).

The api process also needs these; every other process accepts them too, so one environment serves every process of the image:

| Variable | Meaning |
|---|---|
| `PENARIA_PUBLIC_URL` | Required. The address people open, such as `https://home.example.org`: the root of a site, without a path. Requests that change something are refused when the browser says they come from another site (`Origin`), and the session cookie is `Secure` when it is `https`. Its host name is what passkeys belong to |
| `PENARIA_SECRET_KEY` | Required, at least 32 characters, such as the output of `openssl rand -hex 32`. Stored secrets (the mailbox's password, queued email) are encrypted with a key derived from it: keep it, and back it up apart from the database |
| `PENARIA_RETIRED_SECRET_KEYS` | Optional. Earlier values of `PENARIA_SECRET_KEY`, separated by commas, while you rotate it: what they encrypted still opens, and new secrets use the new key. Save the mailbox's password again in Settings, then drop the old key. With several api replicas, first add the new key here on every replica, and only then make it `PENARIA_SECRET_KEY` |
| `PENARIA_S3__BUCKET`, `..._ACCESS_KEY_ID`, `..._SECRET_ACCESS_KEY`, `..._ENDPOINT`, `..._REGION`, `..._PATH_STYLE` | Optional storage for photos and documents ("Files and the worker" below); the api, worker and migrate processes use it |
| `PENARIA_FILES__MAX_SIZE` | Optional. The largest file, in bytes; 52428800 (50 MB) by default. Give the web image the same value |
| `PENARIA_AUTH__OIDC__ISSUER`, `..._CLIENT_ID`, `..._CLIENT_SECRET`, `..._ALLOW_SIGN_UP`, `..._NAME`, `..._SCOPES` | Optional sign-in with your OpenID Connect provider, such as Authentik or Keycloak ("Sign-in with your identity provider" below) |
| `PENARIA_MAIL__HOST`, `..._PORT`, `..._SECURITY` (`starttls`, `tls` or `none`), `..._USERNAME`, `..._PASSWORD`, `..._FROM_ADDRESS`, `..._FROM_NAME` | Optional outgoing email. Usually an install admin connects the mailbox in the web app (Settings); set these to manage it as configuration instead. With `PENARIA_MAIL__HOST` set, every mail setting comes from the environment (`..._FROM_ADDRESS` is then required, and the port defaults to 587, 465 or 25 by the security) and the web app shows them locked |

The Compose install (`deploy/compose`) sets this up by itself: only `penaria-web` reaches the server there. Otherwise, behind a reverse proxy, let the server trust its `X-Forwarded-For`, so that the session list and the sign-in limits see people's addresses rather than the proxy's: `PENARIA_SERVER__UVICORN__FORWARDED_ALLOW_IPS=<the proxy's address>`. Without it everyone signs in from the proxy's address, and five wrong passwords by anyone make everyone wait.

## HTTP API

REST under `/api/v1`; the OpenAPI document is at `/system/openapi.json`, Swagger UI at `/system/docs`. The same document is committed as `openapi.json` (`make openapi` exports it without a database), and the web app generates its API types from it; a unit test fails when the committed file no longer matches the code. So far: setup and signing in (`/setup`, `/sign-in`, `/sign-in/second-factor`, `/sign-in/passkey`, `/sign-out`), signing in with the operator's provider (`/auth/config`, `/auth/oidc:sign-in`, `:accept-invitation`, `/auth/oidc/callback`, `/me/sign-in-methods`, `/me/external-identities`, `:link`, `/me/reauthenticate/oidc`), recovery (`/mail`, `/password-reset:request`, `:preview`, `/password-reset`, `/email-verifications:confirm`), the signed-in account, its email, sessions, passkeys and second factor (`/me`, `/me/email`, `/me/password`, `/me/sessions`, `/me/passkeys`, `/me/second-factor`, `/me/totp`, `:confirm`, `/me/totp/recovery-codes`, `/me/reauthenticate`), the install's settings for its admins (`/install/mail`, `:test`, `/status`, `/messages`), the account's homes (`/homes`), a home's people (`/homes/{id}/roles`, `/members`, `/members/{id}:reset-link`, `/grants/{id}`, `:leave`, `/invitations`, `/guest-links`, `/devices`), accepting invitations (`/invitations:preview`, `:accept`, `:accept-new-account`), guest visits (`/guest-sessions`, `/guest`), the home tree (`/homes/{id}/entities`, `/entities/{id}`, with `:move`, `:archive`, `:restore`, `:verify` and `/history`), files (`/config/files`, `/entities/{id}/files`, `/entities/{id}/files/{file}`, `/entities/{id}/cover`, `/covers:find`, `/files/{file}`, `:restore`, `/content`, `/preview/320` and `/preview/1600`, `/homes/{id}/files/trash`). Errors are `application/problem+json` with a stable `code`; a request without a session answers 401 with the code `unauthenticated`.

## Files and the worker

Photos and documents are attached to things and places (`docs/design/documents.md`). They need S3-compatible storage; without `PENARIA_S3__*` the server runs, `/config/files` says files are off, an upload answers `409 files_off`, and the worker idles.

| Variable | Meaning |
|---|---|
| `PENARIA_S3__BUCKET`, `..._ACCESS_KEY_ID`, `..._SECRET_ACCESS_KEY` | Required to keep files. The bucket is Penaria's own: `migrate upgrade` creates it when it is missing |
| `PENARIA_S3__ENDPOINT` | The storage's address, such as `http://s3:9000`; without it, AWS S3 in the region |
| `PENARIA_S3__REGION` | `us-east-1` by default |
| `PENARIA_S3__PATH_STYLE` | `true` by default: the bucket in the path, as self-hosted storages expect. `false` puts it in the host name |

An upload (`POST /api/v1/entities/{id}/files?kind=photo`, a multipart form with the file in `file`) streams into storage as an object nothing serves. The worker then takes it: it removes all metadata of JPEG, PNG and WebP images without recompressing them (the orientation and the colour profile stay), converts HEIC to JPEG, draws WebP previews of 320 and 1600 pixels (of a PDF's first page too), and marks the file `ready`, or `failed` with a reason. Each image and PDF is parsed in a child process with no environment of the server's, a limit of memory and a deadline of two minutes, so a crafted file takes neither the worker nor the API down; a file that crashes it three times fails. Everything else is stored byte for byte and only ever downloaded.

Run as many workers as you like: each file is taken under a ten-minute lease (`SELECT … FOR UPDATE SKIP LOCKED`). The worker also deletes what has been in the trash for 30 days, and uploads that no file waits for after a day. `python -m penaria.apps.worker.health` exits 0 while the worker makes its passes, for a container's health check. An interrupted multipart upload leaves parts behind: SILO and MinIO drop them after a day; on AWS S3 add a lifecycle rule that aborts incomplete multipart uploads.

## Sign-in and the first start

The web app signs in with a passkey, or with a username and a password, and keeps a session cookie, `penaria_session` (`docs/design/sign-in.md`). Until an account exists, the api process prints a one-time setup token to its log on every start, and the setup screen asks for it before making the first account, the install's admin:

```sh
docker compose logs penaria-server | grep "setup token"   # a Compose install
make run-api                                               # development: the token is in the output
```

Each start before setup prints a new token and the old one stops working; with several api replicas, use the token of the one that started last. An install from before sign-in keeps its data: setup turns its one local user, with its homes, into the new account.

People join a home through invitations: whoever manages the home's people makes a link (`<PENARIA_PUBLIC_URL>/invite/<token>`) with a role, a place and an end of access, and the person accepts it with their account or makes one through it; there is no open sign-up. Guest links (`<PENARIA_PUBLIC_URL>/guest/<token>`) need no account: opening one gives the browser a guest session that sees only guest-visible things and ends when the link expires or is revoked. Both links are shown once, when made: the server keeps only hashes of their tokens. The rules are in `docs/design/sign-in.md`, section 14.

Devices and integrations (a smart mirror, a backup script, another service) sign in with a token of their own: whoever manages a home's people adds one on the People page with a name, a role and a place, and the token, `pnr_` and 43 letters and digits, is shown once. Every request sends it as `Authorization: Bearer pnr_…` and acts as the device, within its role; it reaches no account, people or install endpoint. A token never expires; the People page shows when and from which address each was last used, and revoking it there ends its access at once:

```sh
curl -H "Authorization: Bearer pnr_…" https://home.example.org/api/v1/homes
```

Penaria reads only bearer tokens that start with `pnr_` and leaves any other `Authorization` header alone, so browsers work behind a reverse proxy that signs people in with it (basic auth, say). A device cannot send that header twice, though: let requests that carry `Bearer pnr_…` past the proxy's own check, for example in nginx:

```nginx
map $http_authorization $penaria_auth {
    ~*^bearer\s+pnr_  off;
    default           "Penaria";
}
auth_basic $penaria_auth;
```

The proxy cannot check the token, so any request that carries such a header passes it, whatever page it asks for: Penaria's own sign-in and its limits are then the only guard of the whole site, as without the proxy.

A person who makes a device must hold the access to give its role without an end: a member whose access ends cannot add one.

Passkeys belong to the host name of `PENARIA_PUBLIC_URL`: browsers offer them only on `https` with a domain name, or on `localhost`, so an install opened at a plain IP address signs in with passwords only. Changing the host name later makes every passkey unusable (people sign in with their password and add a new one). Adding or removing a passkey needs a sign-in within the last 10 minutes; the web app asks for the password or a passkey again when it is older.

Two-step sign-in: an account may add an authenticator app (TOTP: six digits, 30 seconds, as Google Authenticator, 1Password and the like make them) on its account page, and then signing in with the password asks for a code from it too; ten single-use recovery codes stand in for the phone when it is lost. Signing in with a passkey asks for no code. The app's secret is stored encrypted with `PENARIA_SECRET_KEY`, so changing that key without keeping the old one in `PENARIA_RETIRED_SECRET_KEYS` leaves only the recovery codes working. Owners of a home and the install's admins who sign in with a password must have an authenticator app or a passkey: until they add one, they are asked for it right after signing in, and handing a home over, changing people's access, making reset links and the install's settings answer `403 second_factor_required` (`docs/design/sign-in.md`, section 16).

## Sign-in with your identity provider

A household that already runs an OpenID Connect provider (Authentik, Keycloak, Zitadel, Dex, a Google Workspace) can let people sign in with it. Register Penaria with the provider as a confidential client with the authorization code flow, and the redirect URI `<PENARIA_PUBLIC_URL>/api/v1/auth/oidc/callback`; then set:

| Variable | Meaning |
|---|---|
| `PENARIA_AUTH__OIDC__ISSUER` | The provider's issuer, exactly as its `/.well-known/openid-configuration` names it, trailing slash and all. `https`, or `http` only for a provider on the same machine |
| `PENARIA_AUTH__OIDC__CLIENT_ID`, `..._CLIENT_SECRET` | The client the provider made for Penaria |
| `PENARIA_AUTH__OIDC__NAME` | Optional. What the button says: "Sign in with <name>"; the issuer's host name by default |
| `PENARIA_AUTH__OIDC__ALLOW_SIGN_UP` | Optional, `false` by default. With `true`, anyone the provider signs in gets an account; with `false`, a person needs an invitation, and accepting it with "Join with <name>" links their identity |
| `PENARIA_AUTH__OIDC__SCOPES` | Optional, `openid profile email` by default |

```sh
# Authentik: Applications → Providers → OAuth2/OpenID Provider, client type Confidential
PENARIA_AUTH__OIDC__ISSUER=https://auth.example.org/application/o/penaria/
PENARIA_AUTH__OIDC__CLIENT_ID=<client id>
PENARIA_AUTH__OIDC__CLIENT_SECRET=<client secret>
PENARIA_AUTH__OIDC__NAME=Authentik

# Keycloak: a client with Client authentication on and Standard flow
PENARIA_AUTH__OIDC__ISSUER=https://sso.example.org/realms/home
PENARIA_AUTH__OIDC__CLIENT_ID=penaria
PENARIA_AUTH__OIDC__CLIENT_SECRET=<client secret>
PENARIA_AUTH__OIDC__NAME=Keycloak
```

People link their identity on the account page, or join through an invitation with it. Penaria keys an identity by the issuer and the provider's `sub`, never by email, and takes the email only when the provider says it checked it; so changing the issuer (moving the provider, renaming an Authentik application) unlinks everyone, and so does removing these variables. Accounts made through the provider have no password: after such a change they sign in again only with a reset link from the operator (`users reset`, below) or a passkey they added. Confirming it is you through the provider needs a provider that reports when the person signed in (`auth_time`), as Authentik and Keycloak do; with one that does not, such as Dex, people confirm with a passkey or a password. Penaria's own rules still apply after the provider: an account with an authenticator app is asked for its code, and owners and admins must have the app or a passkey (`docs/design/sign-in.md`, section 18). If the provider cannot be reached, the button answers that it is unavailable and the details are in the server's log; passwords and passkeys keep working.

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
| Run the worker against the development stack | `make run-worker` |
| Export the OpenAPI document to `openapi.json` | `make openapi` |

The Makefile points every command at the development stack (`scripts/dev/compose.yaml`); set the `PENARIA_DATABASE__*` and `PENARIA_S3__*` variables, or `TEST_DATABASE_URL` and `TEST_S3_URL` for the tests, to use other servers. The tests of files make a bucket of their own for each run and delete it. Migrations run only through the migrate process, never through the bare `alembic` command, and every migration is tested to upgrade, downgrade and upgrade again, and to match the models (`tests/integration/test_migrations.py`).

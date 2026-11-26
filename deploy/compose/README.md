# Penaria at home with Docker Compose

One machine runs everything: PostgreSQL, the Penaria server and the web app. It suits a home server, a NAS or a small VPS, on `amd64` or `arm64`.

| File | What it is |
|---|---|
| `compose.yaml` | The install: `postgres`, `penaria-migrate` (prepares the database, then exits), `penaria-server`, `penaria-web` |
| `compose.https.yaml` | Adds Caddy, which gets and renews an HTTPS certificate by itself |
| `compose.build.yaml` | Builds the images from this checkout instead of pulling released ones |
| `.env.example` | The settings you fill in |

You need Docker Engine with Docker Compose 2.24 or newer.

## Install

<!-- x-release-please-start-version -->
```sh
git clone --depth 1 --branch v0.1.0 https://github.com/AlexeyShalaev/penaria.git
cd penaria/deploy/compose
cp .env.example .env
```
<!-- x-release-please-end -->

Fill in `.env`:

- `PENARIA_PUBLIC_URL`: the address people will open, exactly as they type it.
- `PENARIA_SECRET_KEY`: the output of `openssl rand -hex 32`.
- `POSTGRES_PASSWORD`: the output of `openssl rand -hex 24`.

Then start it and read the one-time setup token from the server's log:

```sh
docker compose up -d
docker compose logs penaria-server | grep "setup token"
```

Open the address, enter the token and create the first account. It manages this install and owns the homes it creates. The token proves you have access to the machine, so nobody who merely finds the address can take the install over. Every restart before setup makes a new token.

Once you own a home, Penaria asks you for a second step: a passkey or an authenticator app (any that makes six-digit codes). Keep the ten recovery codes it shows with the app: they stand in for a lost phone.

## The address and HTTPS

Penaria checks that requests come from `PENARIA_PUBLIC_URL`, so open it at exactly that address: `http://localhost:8080` and `http://127.0.0.1:8080` are two different ones.

- **At home, without a domain.** `PENARIA_PUBLIC_URL=http://<the machine's address>:8080` works on your network. Passkeys stay off there: browsers allow them only on `https` with a host name, or on `localhost`. Use it only on a network you trust, because the traffic is not encrypted.
- **With a domain.** Point the domain at the machine, let ports 80 and 443 reach it, and set `PENARIA_PUBLIC_URL=https://home.example.org` and `PENARIA_DOMAIN=home.example.org` in `.env`. Then run every command with both files:

  ```sh
  docker compose -f compose.yaml -f compose.https.yaml up -d
  ```

  Or put `COMPOSE_FILE=compose.yaml:compose.https.yaml` in `.env` and keep typing `docker compose`.
- **Behind your own reverse proxy.** Send everything to `penaria-web` on port 8080, and tell it which addresses are your proxy's, so it takes the visitor's address from the proxy's `X-Forwarded-For`. Without this everyone appears to come from the proxy, and five wrong passwords by anyone make everyone wait. In a `compose.override.yaml` next to `compose.yaml`:

  ```yaml
  services:
    penaria-web:
      environment:
        PENARIA_TRUSTED_PROXIES: 192.168.1.2   # addresses or networks, comma-separated
  ```

## More settings

The server's other settings, such as sign-in with your identity provider, go into a file named `server.env` in this folder, one `PENARIA_...=value` per line; [the server's README](../../services/server/README.md) lists them. A mailbox for outgoing email is easier to connect in the web app: Settings, as the install's admin.

The server stops at start when it meets a `PENARIA_` setting it does not know, so a misspelt one never goes unnoticed: `docker compose logs penaria-server` names it.

## Back up

Two things hold everything: the database and `PENARIA_SECRET_KEY`. Keep the key apart from the database's backups: together they open the stored secrets.

```sh
docker compose exec postgres pg_dump -U penaria -Fc penaria > penaria-$(date +%F).dump
```

To restore into an empty install (after `docker compose up -d postgres`, with the same `.env`):

```sh
docker compose exec -T postgres pg_restore -U penaria -d penaria --clean --if-exists < penaria-2026-11-27.dump
docker compose up -d
```

## Upgrade

Read "Before you upgrade" in the [release notes](../../CHANGELOG.md), back up, then take the new version's files and start it. The database is brought to the new version by itself.

```sh
git fetch --tags && git checkout v<new version>
docker compose pull
docker compose up -d
```

To go back to the version you had, restore the backup you took before upgrading: an older server does not understand a newer database.

## Day to day

| Task | Command |
|---|---|
| See what runs | `docker compose ps` |
| Read the server's log | `docker compose logs -f penaria-server` |
| Let a locked-out person in: prints a one-time password reset link | `docker compose exec penaria-server python -m penaria.apps.cli users reset <username>` |
| Stop, keeping the data | `docker compose down` |
| Remove everything, the data included | `docker compose down --volumes` |

## From source

To try a change, build the images from the checkout:

```sh
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

`./smoke-test.sh` does this in a Compose project of its own and checks that the install answers; with `--https` it also checks the HTTPS overlay (it needs ports 80 and 443). CI runs it on every pull request.

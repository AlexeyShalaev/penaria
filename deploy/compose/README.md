# Penaria at home with Docker Compose

One machine runs everything: PostgreSQL, storage for photos and documents, the Penaria server, its worker and the web app. It suits a home server, a NAS or a small VPS, on `amd64` or `arm64`.

| File | What it is |
|---|---|
| `compose.yaml` | The install: `postgres`, `s3` (the files, in [SILO](https://silo.pigsty.io)), `penaria-migrate` (prepares the database and the storage, then exits), `penaria-server`, `penaria-worker` (cleans uploaded photos, makes previews, empties the trash), `penaria-web` |
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
- `S3_PASSWORD`: the output of `openssl rand -hex 24`.

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

## Photos and documents

Files are kept in the `s3` service, on its own volume. Only Penaria reaches it: it publishes no port. Before anyone can open a photo, the worker removes its metadata, the place it was taken among it, and converts HEIC to JPEG; PDF and other documents are kept as they are.

A file is at most 50 MB. To change that, set `PENARIA_FILES__MAX_SIZE` (bytes) in `.env`, not in `server.env`: the web app's proxy needs the same number as the server. A reverse proxy of your own in front of Penaria must let uploads of that size through (in nginx, `client_max_body_size`).

## More settings

The server's other settings, such as sign-in with your identity provider, go into a file named `server.env` in this folder, one `PENARIA_...=value` per line; [the server's README](../../services/server/README.md) lists them. The worker does not read it: it opens what strangers made, so it is given only where the database and the files are. A mailbox for outgoing email is easier to connect in the web app: Settings, as the install's admin.

The server stops at start when it meets a `PENARIA_` setting it does not know, so a misspelt one never goes unnoticed: `docker compose logs penaria-server` names it.

## Back up

Three things hold everything: the database, the files and `PENARIA_SECRET_KEY`. Keep the key apart from the backups: with the database it opens the stored secrets.

Stop what writes, so the database and the files agree with each other, then copy both. The files are copied from the stopped storage, as a folder:

```sh
docker compose stop penaria-web penaria-server penaria-worker s3
docker compose exec -T postgres pg_dump -U penaria -Fc penaria > penaria-$(date +%F).dump
docker compose cp s3:/data ./files-$(date +%F)
docker compose up -d
```

To restore into an empty install, with the same `.env` and the date of the backup in place of `2026-11-27`:

```sh
docker compose up -d --wait postgres
docker compose exec -T postgres pg_restore -U penaria -d penaria --clean --if-exists < penaria-2026-11-27.dump
docker compose create s3
docker compose cp ./files-2026-11-27/. s3:/data
docker compose up -d
```

## Upgrade

Read "Before you upgrade" in the [release notes](../../CHANGELOG.md), back up, then take the new version's files and start it. The database is brought to the new version by itself.

```sh
git fetch --tags && git checkout v<new version>
docker compose pull
docker compose up -d
```

**From 0.1.0**, which kept no files, two things differ. Back up before you check out the new version, and the database is all there is to back up:

```sh
docker compose exec -T postgres pg_dump -U penaria -Fc penaria > penaria-$(date +%F).dump
```

Then, before starting the new version, add the storage's password to `.env`:

```sh
printf '\nS3_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> .env
```

To go back to the version you had: an older server does not understand a newer database, so restore the backup you took before upgrading into an empty database. Stop everything **while the new version's files are still checked out**, so that the containers the old version does not know are removed too, delete the data (have the backup first), then check out the old version and restore as its guide says:

```sh
docker compose down --remove-orphans
docker volume rm penaria_postgres penaria_s3
git checkout v<old version>
```

## Day to day

| Task | Command |
|---|---|
| See what runs | `docker compose ps` |
| Read the server's log | `docker compose logs -f penaria-server` |
| Read the worker's log, such as why a photo failed | `docker compose logs -f penaria-worker` |
| Let a locked-out person in: prints a one-time password reset link | `docker compose exec penaria-server python -m penaria.apps.cli users reset <username>` |
| Stop, keeping the data | `docker compose down` |
| Remove everything, the data included | `docker compose down --volumes` |

## From source

To try a change, build the images from the checkout:

```sh
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

`./smoke-test.sh` does this in a Compose project of its own and checks that the install answers; with `--https` it also checks the HTTPS overlay (it needs ports 80 and 443). CI runs it on every pull request.

# Penaria web

The web app of Penaria: a React PWA for phones and desktops.

The code follows Feature-Sliced Design: `src/app` (bootstrap), `pages`, `widgets`, `features`, `entities` and `shared` (UI kit, i18n, API client), each layer importing only from the layers below it. The design tokens in `src/shared/ui/tokens.css` are the only source of colours, sizes and shadows.

Every user-facing string goes through i18n (`src/shared/i18n`), with English and Russian translations; a test fails when a key is missing from either.

Routing is `react-router` (declarative mode), server data goes through `@tanstack/react-query`, icons come from `lucide-react`.

## API client

The types of the API are generated from the server's OpenAPI document, `services/server/openapi.json`, into `src/shared/api/schema.gen.ts` by `openapi-typescript`; `openapi-fetch` makes the typed calls (`src/shared/api`). Never edit the generated file. After a change to the server's API:

```sh
make -C ../server openapi   # export the document
make api                    # regenerate the types
```

`make check` (and CI) fails when the generated types do not match the document.

The app calls the API on its own origin (`/api`, `/system`): the dev server proxies them to the server on :8000, and an install must route them to `penaria-server` the same way in front of `penaria-web`.

## Signing in

The server keeps the session in an `HttpOnly` cookie, so the app holds no token: it asks `/api/v1/me` who is signed in. Every page but the setup and sign-in screens sits behind `RequireAccount` (`src/app`), which sends a visitor without a session to sign in, or to the setup screen on a fresh install, and back to the page afterwards. Any call that answers `401` with the code `unauthenticated` signs the app out the same way: the query client calls `forgetAccount` of the account entity, wired in `src/app/App.tsx`.

Passkeys go through `navigator.credentials` in `src/shared/lib/webauthn.ts`, which converts the server's JSON options and the browser's answers; the passkey button and the suggestion to add one show only where the browser offers WebAuthn (a secure page: `https`, or `localhost`). Tests stand in for the browser with `src/test/webauthn.ts`.

In development, `make -C ../server run-api` prints the setup token of a fresh database; the server expects the dev server's address, `http://localhost:5173`, as `PENARIA_PUBLIC_URL`, so open the app there.

## Commands

| Task                    | Command        |
| ----------------------- | -------------- |
| Install                 | `make install` |
| Format                  | `make fmt`     |
| Lint, formatting, types | `make check`   |
| Test                    | `make test`    |
| Dev server              | `make dev`     |
| Build                   | `make build`   |
| Regenerate API types    | `make api`     |

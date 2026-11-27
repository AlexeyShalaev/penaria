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

The app calls the API on its own origin (`/api`). The dev server proxies it to the server on :8000. The image does the same: its nginx passes `/api/` on to `PENARIA_API_UPSTREAM` (`http://penaria-server:8000` by default, the server's name in the Compose install), with the visitor's address in `X-Forwarded-For`. Behind another reverse proxy, `PENARIA_TRUSTED_PROXIES` lists that proxy's addresses or networks, comma-separated, so the address is the visitor's and not the proxy's (`nginx.conf.template`, `trusted-proxies.sh`). Uploads of files may be as large as `PENARIA_FILES__MAX_SIZE` (bytes, 50 MB by default), which must be the same as the server's (`upload-limit.envsh`); every other request keeps nginx's 1 MB.

## Signing in

The server keeps the session in an `HttpOnly` cookie, so the app holds no token: it asks `/api/v1/me` who is signed in. Every page but the setup, sign-in, invitation and guest screens sits behind `RequireAccount` (`src/app`), which sends a visitor without a session to sign in, or to the setup screen on a fresh install, and back to the page afterwards. Any call that answers `401` with the code `unauthenticated` signs the app out the same way: the query client calls `forgetAccount` of the account entity, wired in `src/app/App.tsx`.

The invitation and guest pages: `/invite/:token` shows what an invitation offers and accepts it with the signed-in account, or makes an account through it. `/guest/:token` opens a guest link: it exchanges the token for a guest session and moves on to `/guest`, the guest's read-only view of the home. QR codes of these links are drawn in the browser (`src/shared/ui/QrCode.tsx`, with `uqr`). The People page also lists the home's devices and integrations: adding one shows its token once, with a `curl` command that tries it; revoking takes one click.

Recovery and email: `/forgot-password` asks for a reset link by email (the sign-in page links to it when the install sends email), `/reset-password/:token` sets a new password with a link from an email, an admin or the operator, and `/verify-email/:token` confirms the address an account added. The install's admins see Settings (`/settings`): the mailbox the install sends email through, a test email, the connection's status and the mail log. In development, Mailpit of `make dev-up` catches the email (http://localhost:58025); connect it in Settings as the server README says.

Two-step sign-in: signing in with the password answers `202` with a pending sign-in for an account with an authenticator app, and the sign-in page asks for its code or a recovery code (`/sign-in/second-factor`). The account page sets the app up (its QR code is drawn in the browser with `uqr`, like invitation links). An owner or an install admin without a second factor sees a prompt over every page, from `RequireAccount`, until they add a passkey or the app.

Signing in with the operator's provider: when `/api/v1/auth/config` names one, the sign-in page offers "Sign in with <name>", the invitation page "Join with <name>", the account page a "Linked accounts" card and the confirm-it-is-you dialog the provider too. Each asks the server for the provider's address and leaves for it; the provider sends the browser back to the server's callback, which redirects to the page it came from, to `/sign-in` with the second step in the address's fragment for an account with an authenticator app, or to `/sign-in/external?problem=…`, which says what went wrong.

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

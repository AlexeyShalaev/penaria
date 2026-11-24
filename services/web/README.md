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

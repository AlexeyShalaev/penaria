# Penaria web

The web app of Penaria: a React PWA for phones and desktops.

The code follows Feature-Sliced Design: `src/app` (bootstrap), `pages`, `widgets`, `features`, `entities` and `shared` (UI kit, i18n, API client), each layer importing only from the layers below it. The design tokens in `src/shared/ui/tokens.css` are the only source of colours, sizes and shadows.

Every user-facing string goes through i18n (`src/shared/i18n`), with English and Russian translations.

## Commands

| Task                    | Command        |
| ----------------------- | -------------- |
| Install                 | `make install` |
| Format                  | `make fmt`     |
| Lint, formatting, types | `make check`   |
| Test                    | `make test`    |
| Dev server              | `make dev`     |
| Build                   | `make build`   |

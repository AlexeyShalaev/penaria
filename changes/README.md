# Release note fragments

Every pull request that changes what users get adds one fragment here: a short TOML file that becomes a line of the release notes. Notes are written in the pull request, while its author still remembers why the change matters, and reviewed with the code.

```sh
make change slug=search-in-manuals type=added
```

```toml
# changes/search-in-manuals.toml
type = "added"
en = "Search finds things by the words in their attached manuals."
ru = "Поиск находит вещи по словам из приложенных инструкций."
```

## Types

| Type | When | Shown as |
|---|---|---|
| `upgrade` | Something a self-hoster must do before or while upgrading: a new or renamed environment variable, a manual migration step, a changed port. Required for every breaking change (`!` in the title). | Before you upgrade |
| `security` | A vulnerability fixed or a security setting changed. | Security |
| `added` | A new capability. | Added |
| `changed` | Existing behaviour works differently. | Changed |
| `deprecated` | Still works, will be removed. | Deprecated |
| `removed` | Gone. | Removed |
| `fixed` | A bug fixed. | Fixed |

One fragment per change; a pull request may add several (a breaking feature usually adds `added` and `upgrade`).

## Writing a note

- Write for a person who runs Penaria at home, not for a developer: what they can do now, what works differently, what they must do. No class names, no internal terms.
- One sentence, two at most, in the present tense: "Search finds…", not "Added search for…".
- `en` and `ru` say the same thing. Both are required: the notes are shown in the app in the user's language.

## When a pull request needs a fragment

CI checks every pull request (`.github/workflows/pull-request.yml`):

- the title is a Conventional Commit;
- a `feat`, `fix` or `perf` pull request, or any breaking one (`feat!:`), adds at least one fragment;
- a breaking pull request adds an `upgrade` fragment.

A `feat`, `fix` or `perf` change users never notice (an internal flag, a fix to unreleased code) takes the `no-changelog` label instead of a fragment.

## What happens next

When release-please opens or updates the release pull request, the release workflow moves every fragment into `release-notes.json` under the new version and regenerates `CHANGELOG.md` from it, in the same pull request. Read the notes there and edit the wording if needed; merging that pull request publishes the release with these notes and the images.

`release-notes.json` is the source of truth; `CHANGELOG.md` and the GitHub release are rendered from it by `scripts/release/notes.py`. Never edit `CHANGELOG.md` by hand.

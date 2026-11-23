#!/usr/bin/env python3
"""Release notes of Penaria: fragments in changes/ -> release-notes.json -> CHANGELOG.md and the GitHub release.

Every pull request with a user-visible change adds a fragment, ``changes/<slug>.toml``::

    type = "added"
    en = "Search finds things by the words in their attached manuals."
    ru = "Поиск находит вещи по словам из приложенных инструкций."

When release-please opens or updates the release pull request, ``collect`` moves the fragments into
``release-notes.json`` under the new version and regenerates ``CHANGELOG.md``. ``release-notes.json``
is the source of truth: the changelog, the GitHub release and the app's "What's new" are rendered
from it. Standard library only, so it runs on any Python 3.11+ without an environment.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The sections of a release in the order they are rendered (Keep a Changelog, plus "upgrade":
# what a self-hoster must do before or while upgrading).
SECTIONS: dict[str, dict[str, str]] = {
    "upgrade": {"en": "Before you upgrade", "ru": "Перед обновлением"},
    "security": {"en": "Security", "ru": "Безопасность"},
    "added": {"en": "Added", "ru": "Новое"},
    "changed": {"en": "Changed", "ru": "Изменено"},
    "deprecated": {"en": "Deprecated", "ru": "Устарело"},
    "removed": {"en": "Removed", "ru": "Удалено"},
    "fixed": {"en": "Fixed", "ru": "Исправлено"},
}
LANGUAGES = ("en", "ru")

# Pull request titles are Conventional Commits: they become the squash commit on master.
TITLE = re.compile(
    r"^(?P<type>feat|fix|perf|refactor|docs|test|build|ci|chore|revert|style)"
    r"(?:\((?P<scope>[a-z0-9][a-z0-9-]*)\))?(?P<breaking>!)?: \S.*$"
)
# Types whose pull requests change what users get, and so need a fragment.
USER_VISIBLE_TYPES = frozenset({"feat", "fix", "perf"})
NO_CHANGELOG_LABEL = "no-changelog"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CHANGELOG_HEADER = """# Changelog

All notable changes to Penaria, newest first. This file is generated from `release-notes.json` by
`scripts/release/notes.py`: do not edit it by hand. A change gets here through a fragment in
`changes/` (see `changes/README.md`).
"""


class NotesError(Exception):
    """A fragment, the notes file or a pull request breaks the rules; the message says how."""


@dataclass(frozen=True, slots=True)
class Paths:
    root: Path

    @property
    def changes(self) -> Path:
        return self.root / "changes"

    @property
    def notes(self) -> Path:
        return self.root / "release-notes.json"

    @property
    def changelog(self) -> Path:
        return self.root / "CHANGELOG.md"


# ── Fragments ────────────────────────────────────────────────────────────────


def fragment_files(paths: Paths) -> list[Path]:
    return sorted(paths.changes.glob("*.toml"))


def read_fragment(path: Path) -> dict[str, str]:
    if not SLUG.match(path.stem):
        raise NotesError(
            f"{path.name}: the name must be lowercase words joined by hyphens, like search-in-manuals.toml"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise NotesError(f"{path.name}: not valid TOML: {error}") from error
    unknown = set(data) - {"type", *LANGUAGES}
    if unknown:
        raise NotesError(f"{path.name}: unknown keys {sorted(unknown)}; a fragment has type, en and ru")
    kind = data.get("type")
    if kind not in SECTIONS:
        raise NotesError(f"{path.name}: type must be one of {', '.join(SECTIONS)}, not {kind!r}")
    entry = {"type": kind}
    for language in LANGUAGES:
        text = data.get(language)
        if not isinstance(text, str) or not text.strip():
            raise NotesError(f"{path.name}: {language} must be a non-empty string")
        entry[language] = " ".join(text.split())
    return entry


def read_fragments(paths: Paths) -> list[tuple[Path, dict[str, str]]]:
    return [(path, read_fragment(path)) for path in fragment_files(paths)]


def new_fragment(paths: Paths, slug: str, kind: str) -> Path:
    if not SLUG.match(slug):
        raise NotesError(f"{slug!r}: use lowercase words joined by hyphens")
    if kind not in SECTIONS:
        raise NotesError(f"type must be one of {', '.join(SECTIONS)}")
    path = paths.changes / f"{slug}.toml"
    if path.exists():
        raise NotesError(f"{path.relative_to(paths.root)} already exists")
    path.write_text(
        f'type = "{kind}"\n'
        'en = "What changed for the user, in one sentence they understand."\n'
        'ru = "То же по-русски."\n',
        encoding="utf-8",
    )
    return path


# ── release-notes.json ───────────────────────────────────────────────────────


def load_notes(paths: Paths) -> list[dict]:
    if not paths.notes.exists():
        return []
    data = json.loads(paths.notes.read_text(encoding="utf-8"))
    releases = data.get("releases")
    if not isinstance(releases, list):
        raise NotesError('release-notes.json: expected {"releases": [...]}')
    for release in releases:
        validate_release(release)
    return releases


def validate_release(release: dict) -> None:
    version = release.get("version", "")
    if not VERSION.match(str(version)):
        raise NotesError(f"release-notes.json: bad version {version!r}")
    if not DATE.match(str(release.get("date", ""))):
        raise NotesError(f"release-notes.json: {version}: bad date {release.get('date')!r}")
    notes = release.get("notes")
    if not isinstance(notes, dict) or set(notes) - set(SECTIONS):
        raise NotesError(f"release-notes.json: {version}: notes must map sections ({', '.join(SECTIONS)}) to lists")
    for section, items in notes.items():
        for item in items:
            if set(item) != set(LANGUAGES) or not all(isinstance(item[lang], str) and item[lang] for lang in LANGUAGES):
                raise NotesError(f"release-notes.json: {version}: every {section} note needs en and ru")


def save_notes(paths: Paths, releases: list[dict]) -> None:
    text = json.dumps({"releases": releases}, ensure_ascii=False, indent=2)
    paths.notes.write_text(text + "\n", encoding="utf-8")


def collect(paths: Paths, version: str, date: str) -> int:
    """Move the fragments into the release ``version``; return how many were moved."""
    if not VERSION.match(version):
        raise NotesError(f"bad version {version!r}")
    if not DATE.match(date):
        raise NotesError(f"bad date {date!r}, expected YYYY-MM-DD")
    releases = load_notes(paths)
    fragments = read_fragments(paths)
    release = next((r for r in releases if r["version"] == version), None)
    if release is None:
        release = {"version": version, "date": date, "notes": {}}
        releases.insert(0, release)
    release["date"] = date
    for _, fragment in fragments:
        release["notes"].setdefault(fragment["type"], []).append({lang: fragment[lang] for lang in LANGUAGES})
    release["notes"] = {section: release["notes"][section] for section in SECTIONS if section in release["notes"]}
    save_notes(paths, releases)
    for path, _ in fragments:
        path.unlink()
    write_changelog(paths, releases)
    return len(fragments)


# ── Rendering ────────────────────────────────────────────────────────────────


def render_sections(release: dict, language: str, heading: str) -> list[str]:
    lines: list[str] = []
    notes = release["notes"]
    if not notes:
        return [{"en": "No user-facing changes.", "ru": "Изменений для пользователей нет."}[language], ""]
    for section, titles in SECTIONS.items():
        if section in notes:
            lines += [f"{heading} {titles[language]}", ""]
            lines += [f"- {item[language]}" for item in notes[section]]
            lines.append("")
    return lines


def render_changelog(releases: list[dict]) -> str:
    lines = [CHANGELOG_HEADER]
    for release in releases:
        lines += [f"## {release['version']} ({release['date']})", ""]
        lines += render_sections(release, "en", "###")
    return "\n".join(lines).rstrip() + "\n"


def write_changelog(paths: Paths, releases: list[dict]) -> None:
    paths.changelog.write_text(render_changelog(releases), encoding="utf-8")


def render_github_release(releases: list[dict], version: str) -> str:
    release = next((r for r in releases if r["version"] == version), None)
    if release is None:
        raise NotesError(f"release-notes.json has no release {version}")
    lines = render_sections(release, "en", "###")
    lines += ["<details>", "<summary>По-русски</summary>", ""]
    lines += render_sections(release, "ru", "###")
    lines += ["</details>"]
    return "\n".join(lines).rstrip() + "\n"


# ── Checks ───────────────────────────────────────────────────────────────────


def check_tree(paths: Paths) -> None:
    """Every fragment is valid, the notes file is valid and the changelog matches it."""
    read_fragments(paths)
    releases = load_notes(paths)
    expected = render_changelog(releases)
    actual = paths.changelog.read_text(encoding="utf-8") if paths.changelog.exists() else ""
    if actual != expected:
        raise NotesError("CHANGELOG.md does not match release-notes.json: run `make changelog`")


def changed_fragments(paths: Paths, base: str) -> list[Path]:
    """Fragments the pull request adds or changes against ``base``."""
    output = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--", "changes/*.toml"],
        cwd=paths.root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [paths.root / line for line in output.splitlines() if line]


def check_pull_request(title: str, labels: set[str], fragments: list[dict[str, str]]) -> str:
    """Check the title and that a user-visible change comes with its notes; return a summary."""
    match = TITLE.match(title)
    if not match:
        raise NotesError(
            f"the title {title!r} is not a Conventional Commit: <type>(<scope>)?!?: <description>, "
            "type one of feat, fix, perf, refactor, docs, test, build, ci, chore, revert, style"
        )
    breaking = bool(match["breaking"])
    needs_notes = breaking or match["type"] in USER_VISIBLE_TYPES
    if NO_CHANGELOG_LABEL in labels:
        if fragments:
            raise NotesError(
                f"the pull request has the {NO_CHANGELOG_LABEL} label but adds fragments: drop one or the other"
            )
        return f"{NO_CHANGELOG_LABEL}: no release notes"
    if needs_notes and not fragments:
        raise NotesError(
            f"a {match['type']}{'!' if breaking else ''} pull request changes what users get: add a fragment "
            f"(`make change slug=<what-changed> type=<{'|'.join(SECTIONS)}>`), "
            f"or the {NO_CHANGELOG_LABEL} label when users see no difference"
        )
    if breaking and not any(fragment["type"] == "upgrade" for fragment in fragments):
        raise NotesError("a breaking change needs an upgrade fragment: what self-hosters must do before upgrading")
    return f"{len(fragments)} fragment(s)"


def check_release_pull_request(paths: Paths, version: str) -> None:
    if fragment_files(paths):
        raise NotesError("the release pull request still has fragments in changes/: collect has not run")
    if not any(r["version"] == version for r in load_notes(paths)):
        raise NotesError(f"release-notes.json has no release {version}")
    check_tree(paths)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="create a fragment to fill in")
    new.add_argument("slug")
    new.add_argument("--type", required=True, choices=list(SECTIONS))

    commands.add_parser("check", help="validate the fragments, release-notes.json and CHANGELOG.md")

    pr = commands.add_parser("check-pr", help="check a pull request's title and its release notes")
    pr.add_argument("--title", required=True)
    pr.add_argument("--labels", default="", help="comma-separated")
    pr.add_argument("--base", required=True, help="the git ref the pull request merges into")

    release = commands.add_parser("check-release", help="check the release pull request of a version")
    release.add_argument("--version", required=True)

    coll = commands.add_parser("collect", help="move the fragments into a release")
    coll.add_argument("--version", required=True)
    coll.add_argument("--date", required=True)

    changelog = commands.add_parser("changelog", help="regenerate CHANGELOG.md from release-notes.json")
    changelog.add_argument("--check", action="store_true")

    render = commands.add_parser("render", help="print the GitHub release body of a version")
    render.add_argument("--version", required=True)

    args = parser.parse_args(argv)
    paths = Paths(args.root)
    try:
        match args.command:
            case "new":
                path = new_fragment(paths, args.slug, args.type)
                print(f"created {path.relative_to(paths.root)}: fill in en and ru")
            case "check":
                check_tree(paths)
                print(f"ok: {len(fragment_files(paths))} fragment(s) waiting for the next release")
            case "check-pr":
                check_tree(paths)
                labels = {label.strip() for label in args.labels.split(",") if label.strip()}
                fragments = [read_fragment(path) for path in changed_fragments(paths, args.base)]
                print("ok:", check_pull_request(args.title, labels, fragments))
            case "check-release":
                check_release_pull_request(paths, args.version)
                print(f"ok: release {args.version} has its notes")
            case "collect":
                moved = collect(paths, args.version, args.date)
                print(f"collected {moved} fragment(s) into {args.version}")
            case "changelog":
                if args.check:
                    check_tree(paths)
                    print("ok: CHANGELOG.md matches release-notes.json")
                else:
                    write_changelog(paths, load_notes(paths))
            case "render":
                sys.stdout.write(render_github_release(load_notes(paths), args.version))
    except NotesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

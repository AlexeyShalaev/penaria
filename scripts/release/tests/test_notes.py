import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "notes.py"
spec = importlib.util.spec_from_file_location("notes", SCRIPT)
assert spec and spec.loader
notes = importlib.util.module_from_spec(spec)
sys.modules["notes"] = notes
spec.loader.exec_module(notes)


@pytest.fixture
def paths(tmp_path: Path) -> "notes.Paths":
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "README.md").write_text("not a fragment\n")
    return notes.Paths(tmp_path)


def fragment(paths: "notes.Paths", slug: str, kind: str, en: str = "English text.", ru: str = "Русский текст.") -> Path:
    path = paths.changes / f"{slug}.toml"
    path.write_text(f'type = "{kind}"\nen = "{en}"\nru = "{ru}"\n', encoding="utf-8")
    return path


# ── Fragments ────────────────────────────────────────────────────────────────


def test_fragment_is_read_with_whitespace_folded(paths):
    path = paths.changes / "search.toml"
    path.write_text('type = "added"\nen = """Search finds\n  things."""\nru = "Поиск."\n', encoding="utf-8")

    assert notes.read_fragment(path) == {"type": "added", "en": "Search finds things.", "ru": "Поиск."}


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("Bad_Name.toml", 'type = "added"\nen = "a"\nru = "б"\n', "lowercase words"),
        ("x.toml", 'type = "new"\nen = "a"\nru = "б"\n', "type must be one of"),
        ("x.toml", 'type = "added"\nen = "a"\n', "ru must be a non-empty string"),
        ("x.toml", 'type = "added"\nen = " "\nru = "б"\n', "en must be a non-empty string"),
        ("x.toml", 'type = "added"\nen = "a"\nru = "б"\nissue = 1\n', "unknown keys"),
        ("x.toml", "type = \n", "not valid TOML"),
    ],
)
def test_bad_fragment_is_rejected(paths, name, content, message):
    path = paths.changes / name
    path.write_text(content, encoding="utf-8")

    with pytest.raises(notes.NotesError, match=message):
        notes.read_fragment(path)


def test_new_fragment_is_a_valid_template(paths):
    path = notes.new_fragment(paths, "search-in-manuals", "added")

    assert notes.read_fragment(path)["type"] == "added"
    with pytest.raises(notes.NotesError, match="already exists"):
        notes.new_fragment(paths, "search-in-manuals", "added")


# ── collect ──────────────────────────────────────────────────────────────────


def test_collect_moves_fragments_into_the_release_in_section_order(paths):
    fragment(paths, "b-fix", "fixed", en="Fixed it.", ru="Исправили.")
    fragment(paths, "a-feature", "added", en="Added it.", ru="Добавили.")
    fragment(paths, "c-upgrade", "upgrade", en="Set FOO.", ru="Задайте FOO.")

    moved = notes.collect(paths, "0.2.0", "2026-12-01")

    assert moved == 3
    assert notes.fragment_files(paths) == []
    [release] = notes.load_notes(paths)
    assert release["version"] == "0.2.0"
    assert list(release["notes"]) == ["upgrade", "added", "fixed"]
    assert release["notes"]["added"] == [{"en": "Added it.", "ru": "Добавили."}]
    notes.check_tree(paths)


def test_collect_puts_the_new_release_first_and_extends_an_existing_one(paths):
    fragment(paths, "one", "added")
    notes.collect(paths, "0.1.0", "2026-11-01")
    fragment(paths, "two", "fixed")
    notes.collect(paths, "0.2.0", "2026-12-01")
    fragment(paths, "three", "fixed")

    notes.collect(paths, "0.2.0", "2026-12-02")

    releases = notes.load_notes(paths)
    assert [r["version"] for r in releases] == ["0.2.0", "0.1.0"]
    assert releases[0]["date"] == "2026-12-02"
    assert len(releases[0]["notes"]["fixed"]) == 2


def test_collect_without_fragments_makes_an_empty_release(paths):
    notes.collect(paths, "0.1.1", "2026-11-02")

    assert "No user-facing changes." in paths.changelog.read_text(encoding="utf-8")


# ── Rendering and the tree check ─────────────────────────────────────────────


def test_changelog_and_github_release_render_both_languages(paths):
    fragment(paths, "sec", "security", en="Patched CVE.", ru="Закрыли CVE.")
    notes.collect(paths, "1.0.0", "2026-12-01")

    changelog = paths.changelog.read_text(encoding="utf-8")
    body = notes.render_github_release(notes.load_notes(paths), "1.0.0")

    assert "## 1.0.0 (2026-12-01)\n\n### Security\n\n- Patched CVE." in changelog
    assert "Закрыли" not in changelog
    assert body.startswith("### Security\n\n- Patched CVE.")
    assert "<summary>По-русски</summary>" in body
    assert "### Безопасность\n\n- Закрыли CVE." in body


def test_hand_edited_changelog_fails_the_check(paths):
    notes.collect(paths, "0.1.0", "2026-11-01")
    paths.changelog.write_text("edited\n", encoding="utf-8")

    with pytest.raises(notes.NotesError, match="does not match"):
        notes.check_tree(paths)


def test_bad_notes_file_fails_the_check(paths):
    paths.notes.write_text(json.dumps({"releases": [{"version": "1", "date": "x", "notes": {}}]}), encoding="utf-8")

    with pytest.raises(notes.NotesError, match="bad version"):
        notes.check_tree(paths)


# ── Pull requests ────────────────────────────────────────────────────────────

ADDED = {"type": "added", "en": "a", "ru": "б"}
UPGRADE = {"type": "upgrade", "en": "a", "ru": "б"}


@pytest.mark.parametrize(
    ("title", "labels", "fragments"),
    [
        ("feat(registry): add aspects", set(), [ADDED]),
        ("fix: keep the session", set(), [ADDED]),
        ("refactor(registry): split the repository", set(), []),
        ("chore(deps): bump fastapi", set(), []),
        ("feat: internal flag plumbing", {"no-changelog"}, []),
        ("feat(config)!: rename PENARIA_DB", set(), [UPGRADE, ADDED]),
        ("chore(master): release 0.2.0", set(), []),
    ],
)
def test_pull_request_passes(title, labels, fragments):
    notes.check_pull_request(title, labels, fragments)


@pytest.mark.parametrize(
    ("title", "labels", "fragments", "message"),
    [
        ("Add aspects", set(), [], "not a Conventional Commit"),
        ("feat:add aspects", set(), [], "not a Conventional Commit"),
        ("feature: add aspects", set(), [], "not a Conventional Commit"),
        ("feat(registry): add aspects", set(), [], "add a fragment"),
        ("perf: faster search", set(), [], "add a fragment"),
        ("refactor!: drop the v1 API", set(), [], "add a fragment"),
        ("feat!: rename PENARIA_DB", set(), [ADDED], "needs an upgrade fragment"),
        ("feat: x", {"no-changelog"}, [ADDED], "drop one or the other"),
    ],
)
def test_pull_request_fails(title, labels, fragments, message):
    with pytest.raises(notes.NotesError, match=message):
        notes.check_pull_request(title, labels, fragments)


def test_changed_fragments_come_from_git(tmp_path):
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=tmp_path, check=True, capture_output=True
        )

    paths = notes.Paths(tmp_path)
    paths.changes.mkdir()
    git("init", "-q", "-b", "master")
    fragment(paths, "old", "added")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("switch", "-qc", "feature")
    fragment(paths, "new", "fixed")
    (paths.changes / "README.md").write_text("docs\n")
    git("add", "-A")
    git("commit", "-qm", "change")

    assert notes.changed_fragments(paths, "master") == [paths.changes / "new.toml"]


def test_release_pull_request_check(paths):
    fragment(paths, "x", "added")
    with pytest.raises(notes.NotesError, match="still has fragments"):
        notes.check_release_pull_request(paths, "0.1.0")

    notes.collect(paths, "0.1.0", "2026-11-01")
    notes.check_release_pull_request(paths, "0.1.0")
    with pytest.raises(notes.NotesError, match=r"no release 0\.2\.0"):
        notes.check_release_pull_request(paths, "0.2.0")


def test_cli_reports_errors_with_exit_code_1(paths, capsys):
    fragment(paths, "x", "nope")

    assert notes.main(["--root", str(paths.root), "check"]) == 1
    assert "type must be one of" in capsys.readouterr().err

import pytest

from penaria.apps.cli.__main__ import parse
from penaria.apps.cli.settings import Settings

pytestmark = pytest.mark.unit


def test_users_reset_takes_a_username() -> None:
    args = parse(["users", "reset", "Owner"])

    assert (args.group, args.command, args.username) == ("users", "reset", "Owner")


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        parse(["users"])


def test_the_command_line_accepts_the_api_processes_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_RETIRED_SECRET_KEYS", "an-old-key-of-at-least-32-characters")

    assert Settings().public_origin == "http://localhost:5173"

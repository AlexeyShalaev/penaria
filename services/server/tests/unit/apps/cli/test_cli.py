import pytest

from penaria.apps.cli.__main__ import main, parse
from penaria.apps.cli.settings import Settings

pytestmark = pytest.mark.unit


def test_users_reset_takes_a_username() -> None:
    args = parse(["users", "reset", "Owner"])

    assert (args.group, args.command, args.username) == ("users", "reset", "Owner")


def test_users_reset_may_also_turn_the_second_factor_off() -> None:
    assert parse(["users", "reset", "owner"]).disable_second_factor is False
    assert parse(["users", "reset", "owner", "--disable-second-factor"]).disable_second_factor is True


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        parse(["users"])


def test_the_command_line_accepts_the_api_processes_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_RETIRED_SECRET_KEYS", "an-old-key-of-at-least-32-characters")

    assert Settings().public_origin == "http://localhost:5173"


def test_the_command_line_accepts_the_api_servers_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_SERVER__UVICORN__FORWARDED_ALLOW_IPS", "10.0.0.1")

    assert Settings().public_origin == "http://localhost:5173"


def test_a_bad_environment_ends_the_command_with_one_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_PUBLIC_URL", "not a url")

    with pytest.raises(SystemExit, match="the PENARIA_\\* environment is not valid"):
        main(["users", "reset", "owner"])

import pytest

from penaria.apps.migrate.settings import Settings

pytestmark = pytest.mark.unit


def test_migrate_accepts_every_variable_of_the_api_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_MAIL__HOST", "smtp.example.org")
    monkeypatch.setenv("PENARIA_MAIL__FROM_ADDRESS", "home@example.org")
    monkeypatch.setenv("PENARIA_RETIRED_SECRET_KEYS", "an-old-key-of-at-least-32-characters")
    monkeypatch.setenv("PENARIA_SERVER__UVICORN__FORWARDED_ALLOW_IPS", "10.0.0.1")

    assert Settings().database.connection.database == "unit"

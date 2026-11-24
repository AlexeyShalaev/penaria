import pytest

from penaria.apps.api.settings import Settings

pytestmark = pytest.mark.unit


def test_database_settings_come_from_penaria_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_DATABASE__CONNECTION__HOST", "db.home.arpa")
    monkeypatch.setenv("PENARIA_DATABASE__POOL__SIZE", "3")

    database = Settings().database

    assert database.connection.host == "db.home.arpa"
    assert database.pool.size == 3
    assert database.application_name == "penaria"
    assert "unit-secret" not in repr(database)  # the password stays out of logs


def test_variables_without_the_prefix_do_not_leak_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPLICATION_NAME", "someone-else")
    monkeypatch.setenv("CONNECTION__HOST", "elsewhere")

    database = Settings().database

    assert database.application_name == "penaria"
    assert database.connection.host == "localhost"

import pytest
from pydantic import ValidationError

from penaria.apps.api.settings import Settings
from penaria.common.settings import unknown_variables

pytestmark = pytest.mark.unit


def test_reads_variables_with_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_SERVER__PORT", "8123")

    assert Settings().server.port == 8123


def test_ignores_variables_without_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER__PORT", "8123")

    assert Settings().server.port == 8000


@pytest.mark.parametrize("name", ["PENARIA_SEVRER__PORT", "PENARIA_SERVER__PROT", "penaria_logging__levle"])
def test_a_misspelt_variable_stops_the_process(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "1")

    with pytest.raises(ValidationError, match="unknown environment variables"):
        Settings()


def test_known_variables_pass() -> None:
    environ = {
        "PENARIA_SERVER__PORT": "1",
        "PENARIA_LOGGING__LEVEL": "DEBUG",
        "PENARIA_TRACING__COLLECTOR_URL": "http://collector",
        "PENARIA_SERVER__UVICORN_KWARGS__LOOP": "uvloop",
        "PATH": "/bin",
    }

    assert unknown_variables(Settings, environ) == []


def test_the_public_origin_leaves_out_the_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_PUBLIC_URL", "https://Home.Example.org:443/")

    assert Settings().public_origin == "https://home.example.org"


def test_the_public_origin_keeps_another_port() -> None:
    assert Settings().public_origin == "http://localhost:5173"


@pytest.mark.parametrize("url", ["https://example.org/penaria", "https://example.org/?a=1", "ftp://example.org"])
def test_a_public_url_that_is_not_the_root_of_a_site_stops_the_process(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("PENARIA_PUBLIC_URL", url)

    with pytest.raises(ValidationError, match="public_url"):
        Settings()


@pytest.mark.parametrize("name", ["PENARIA_PUBLIC_URL", "PENARIA_SECRET_KEY"])
def test_the_sign_in_settings_are_required(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.delenv(name)

    with pytest.raises(ValidationError, match=name.removeprefix("PENARIA_").lower()):
        Settings()


def test_a_short_secret_key_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENARIA_SECRET_KEY", "too-short")

    with pytest.raises(ValidationError, match="secret_key"):
        Settings()

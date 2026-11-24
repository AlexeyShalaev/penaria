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

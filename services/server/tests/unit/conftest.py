import pytest


@pytest.fixture(autouse=True)
def database_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The required database settings, so the settings build; no unit test connects."""
    monkeypatch.setenv("PENARIA_DATABASE__CONNECTION__PASSWORD", "unit-secret")
    monkeypatch.setenv("PENARIA_DATABASE__CONNECTION__DATABASE", "unit")

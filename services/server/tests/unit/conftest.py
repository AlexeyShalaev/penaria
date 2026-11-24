import pytest


@pytest.fixture(autouse=True)
def required_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The required settings, so the settings build; no unit test connects."""
    monkeypatch.setenv("PENARIA_DATABASE__CONNECTION__PASSWORD", "unit-secret")
    monkeypatch.setenv("PENARIA_DATABASE__CONNECTION__DATABASE", "unit")
    monkeypatch.setenv("PENARIA_PUBLIC_URL", "http://localhost:5173")
    monkeypatch.setenv("PENARIA_SECRET_KEY", "unit-secret-key-of-at-least-32-characters")

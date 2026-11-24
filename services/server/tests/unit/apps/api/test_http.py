import httpx
import pytest
from servicewright import BootstrapContext, HealthRegistry, ServiceContext
from servicewright.testing import FakeContainer, FakeScope, FakeSettings

from penaria.apps.api.entrypoint import build_http
from penaria.apps.api.settings import Settings

pytestmark = pytest.mark.unit


def make_context() -> ServiceContext[FakeSettings, FakeContainer]:
    bootstrap = BootstrapContext(settings=FakeSettings(), service_name="test", container=FakeContainer())
    return ServiceContext(bootstrap=bootstrap, app_scope=FakeScope(), health=HealthRegistry())


async def test_liveness_answers_ok() -> None:
    app = await build_http(Settings()).build_app(make_context())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/system/health/livez")

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("public_url", "warned"),
    [("http://192.168.1.10", True), ("http://localhost:5173", False), ("https://home.example.org", False)],
)
def test_plain_http_beyond_this_machine_is_warned_about(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, public_url: str, warned: bool
) -> None:
    monkeypatch.setenv("PENARIA_PUBLIC_URL", public_url)

    build_http(Settings())

    assert any("plain HTTP" in record.getMessage() for record in caplog.records) is warned


@pytest.mark.parametrize(
    ("public_url", "warned"),
    [
        ("https://192.168.1.10", True),
        ("https://[2001:db8::1]", True),
        ("http://localhost:5173", False),
        ("https://home.example.org", False),
    ],
)
def test_an_address_where_passkeys_cannot_work_is_warned_about(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, public_url: str, warned: bool
) -> None:
    monkeypatch.setenv("PENARIA_PUBLIC_URL", public_url)

    build_http(Settings())

    assert any("passkeys" in record.getMessage() for record in caplog.records) is warned

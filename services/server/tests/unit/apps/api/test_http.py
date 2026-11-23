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

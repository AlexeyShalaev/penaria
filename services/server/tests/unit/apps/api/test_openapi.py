from pathlib import Path

import pytest
from servicewright import BootstrapContext, HealthRegistry, ServiceContext
from servicewright.testing import FakeContainer, FakeScope, FakeSettings

from penaria.apps.api.entrypoint import SERVICE_NAME, build_http
from penaria.apps.api.openapi import DOCUMENT_VERSION, build_schema, render_schema
from penaria.apps.api.settings import Settings

pytestmark = pytest.mark.unit

COMMITTED = Path(__file__).parents[4] / "openapi.json"


def test_the_committed_document_matches_the_code() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == render_schema(), (
        "services/server/openapi.json is stale: run `make -C services/server openapi`"
    )


async def test_the_served_document_is_the_exported_one_but_for_the_version() -> None:
    bootstrap = BootstrapContext(settings=FakeSettings(), service_name=SERVICE_NAME, container=FakeContainer())
    context = ServiceContext(bootstrap=bootstrap, app_scope=FakeScope(), health=HealthRegistry())
    app = await build_http(Settings()).build_app(context)

    served = app.openapi()

    assert {**served, "info": {**served["info"], "version": DOCUMENT_VERSION}} == await build_schema()

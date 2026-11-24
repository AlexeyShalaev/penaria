"""``python -m penaria.apps.api.openapi``: print the API's OpenAPI document, no database needed."""

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from servicewright import BootstrapContext, HealthRegistry, ServiceContext
from servicewright.adapters.fastapi import FastApiEntrypoint, HttpServerSettings
from servicewright.testing import FakeContainer, FakeScope, FakeSettings

from penaria.apps.api.entrypoint import ROUTERS, SERVICE_NAME

# The served document carries the release version; the committed one does not, so a release
# does not make it stale.
DOCUMENT_VERSION = "1"


async def build_schema() -> dict[str, Any]:
    entrypoint = FastApiEntrypoint(config=HttpServerSettings().to_config(version=DOCUMENT_VERSION), routers=ROUTERS)
    # Building the app resolves nothing from the container, so the in-memory doubles stand in for it.
    context = ServiceContext(
        bootstrap=BootstrapContext(settings=FakeSettings(), service_name=SERVICE_NAME, container=FakeContainer()),
        app_scope=FakeScope(),
        health=HealthRegistry(),
    )
    app: FastAPI = await entrypoint.build_app(context)
    return app.openapi()


def render_schema() -> str:
    return json.dumps(asyncio.run(build_schema()), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    print(render_schema(), end="")  # noqa: T201 - the document is the command's output


if __name__ == "__main__":
    main()

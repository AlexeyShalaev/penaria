import os
from collections.abc import AsyncIterator

import httpx
import pytest
from alembic import command
from servicewright import BootstrapContext, HealthRegistry, ServiceContext
from servicewright.adapters.dishka import DishkaContainer
from servicewright.adapters.fastapi import HttpServerSettings
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from penaria.apps.api.container import build_container
from penaria.apps.api.entrypoint import build_http
from penaria.apps.api.settings import Settings
from penaria.common.database import DatabaseSettings
from penaria.migrations.runner import build_config, run_with_connection

# Every table that holds data; CASCADE reaches the rest.
DATA_TABLES = "identity_users, identity_homes, journal_events"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """An empty database the tests may change: ``TEST_DATABASE_URL`` (``make test`` sets it)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set: run `make dev-up` and the tests through `make test`")
    return url


@pytest.fixture
def database_settings(test_database_url: str) -> DatabaseSettings:
    url = make_url(test_database_url)
    return DatabaseSettings.model_validate(
        {
            "connection": {
                "host": url.host,
                "port": url.port,
                "user": url.username,
                "password": url.password,
                "database": url.database,
            },
            "application_name": "penaria-tests",
        }
    )


@pytest.fixture
async def migrated_database(test_database_url: str) -> AsyncIterator[None]:
    """The test database at the latest migration, emptied after each test."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        await run_with_connection(engine, build_config(), lambda config: command.upgrade(config, "head"))
        yield
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {DATA_TABLES} CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture
async def container(migrated_database: None, database_settings: DatabaseSettings) -> AsyncIterator[DishkaContainer]:
    # Its app scope closes it: the api fixture or the test opens one.
    yield build_container(Settings.model_validate({"server": HttpServerSettings(), "database": database_settings}))


@pytest.fixture
async def api(container: DishkaContainer, database_settings: DatabaseSettings) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client of the API process, wired to the test database."""
    settings = Settings.model_validate({"server": HttpServerSettings(), "database": database_settings})
    async with container.app_scope() as app_scope:
        bootstrap = BootstrapContext(settings=settings, service_name="penaria-api", container=container)
        context = ServiceContext(bootstrap=bootstrap, app_scope=app_scope, health=HealthRegistry())
        app = await build_http(settings).build_app(context)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
            yield client

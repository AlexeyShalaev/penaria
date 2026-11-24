import os
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from alembic import command
from fastapi import FastAPI
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
from penaria.features.support.identity.use_cases.setup import IssueSetupToken
from penaria.migrations.runner import build_config, run_with_connection
from tests.smtp import FakeSmtp

# Every table that holds data; CASCADE reaches the rest.
DATA_TABLES = (
    "identity_users, identity_homes, journal_events, identity_setup_tokens, identity_sign_in_failures, "
    "identity_passkey_challenges, identity_tokens, identity_install_settings, identity_mail"
)
PUBLIC_URL = "http://test"
OWNER = {"username": "owner", "display_name": "Owner", "password": "correct horse battery", "locale": "en"}


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
def public_url() -> str:
    """``PENARIA_PUBLIC_URL`` of the tests; a test parametrizes it to run on another."""
    return PUBLIC_URL


@pytest.fixture
def operator_mail() -> dict[str, Any]:
    """``PENARIA_MAIL__*`` of the tests: none; a test overrides it to set the mailbox in the environment."""
    return {}


@pytest.fixture
def settings(database_settings: DatabaseSettings, public_url: str, operator_mail: dict[str, Any]) -> Settings:
    return Settings.model_validate(
        {
            "server": HttpServerSettings(),
            "database": database_settings,
            "public_url": public_url,
            "secret_key": "test-secret-key-of-at-least-32-characters",
            "mail": operator_mail,
        }
    )


@pytest.fixture
async def smtp() -> AsyncIterator[FakeSmtp]:
    server = FakeSmtp()
    await server.start()
    yield server
    await server.stop()


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
async def container(migrated_database: None, settings: Settings) -> AsyncIterator[DishkaContainer]:
    # Its app scope closes it: the api fixture or the test opens one.
    yield build_container(settings)


@pytest.fixture
async def app(container: DishkaContainer, settings: Settings) -> AsyncIterator[FastAPI]:
    """The API process's HTTP app, wired to the test database."""
    async with container.app_scope() as app_scope:
        bootstrap = BootstrapContext(settings=settings, service_name="penaria-api", container=container)
        context = ServiceContext(bootstrap=bootstrap, app_scope=app_scope, health=HealthRegistry())
        yield await build_http(settings).build_app(context)


@pytest.fixture
async def new_client(app: FastAPI, public_url: str) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    """Make HTTP clients of the app, each with its own cookies, like separate browsers."""
    clients: list[httpx.AsyncClient] = []

    def make(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.setdefault("transport", httpx.ASGITransport(app=app))
        client = httpx.AsyncClient(base_url=f"{public_url}/api/v1", **kwargs)
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.fixture
async def setup_token(container: DishkaContainer, app: FastAPI) -> str:
    """The token the server would print on its first start (once the app has opened its scope)."""
    token = await (await container.container.get(IssueSetupToken)).execute()
    assert token is not None
    return token


@pytest.fixture
async def anonymous(new_client: Callable[..., httpx.AsyncClient]) -> httpx.AsyncClient:
    """A client without a session."""
    return new_client()


@pytest.fixture
async def api(new_client: Callable[..., httpx.AsyncClient], setup_token: str) -> httpx.AsyncClient:
    """A client signed in as the install's owner, who completed the setup."""
    client = new_client()
    response = await client.post("/setup", json={**OWNER, "token": setup_token})
    assert response.status_code == 200, response.text
    return client

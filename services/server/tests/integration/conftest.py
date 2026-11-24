import os

import pytest
from sqlalchemy import make_url

from penaria.common.database import DatabaseSettings


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

"""The api with storage, its worker, and a home to keep files in."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest

from penaria.apps.worker.container import build_container
from penaria.apps.worker.settings import Settings as WorkerSettings
from penaria.common.database import DatabaseSettings
from penaria.features.support.documents.use_cases.processing import ProcessNextFile
from penaria.features.support.documents.use_cases.sweep import SweepFiles
from tests.integration.conftest import PUBLIC_URL
from tests.integration.helpers import add_second_factor
from tests.integration.storage import s3_variables, storage  # noqa: F401 - fixtures

Run = Callable[[], Awaitable[None]]


@pytest.fixture
def operator_s3(s3_variables: dict[str, Any]) -> dict[str, Any]:  # noqa: F811 - the fixture
    return s3_variables


@pytest.fixture
async def api(api: httpx.AsyncClient) -> httpx.AsyncClient:
    """The owner, who has a passkey as owners must for owner-level commands (sign-in.md, 4.3)."""
    await add_second_factor(api, PUBLIC_URL)
    return api


@pytest.fixture
def worker_settings(database_settings: DatabaseSettings, operator_s3: dict[str, Any]) -> WorkerSettings:
    return WorkerSettings.model_validate({"database": database_settings, "s3": operator_s3})


@pytest.fixture
async def worker(migrated_database: None, worker_settings: WorkerSettings) -> AsyncIterator[Run]:
    """Run the worker until nothing waits."""
    container = build_container(worker_settings)
    async with container.app_scope() as scope:
        processor = await scope.get(ProcessNextFile)

        async def run() -> None:
            while await processor.execute():
                pass

        yield run


@pytest.fixture
async def sweep(migrated_database: None, worker_settings: WorkerSettings) -> AsyncIterator[Run]:
    container = build_container(worker_settings)
    async with container.app_scope() as scope:
        yield (await scope.get(SweepFiles)).execute

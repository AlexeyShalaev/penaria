"""A bucket of the tests' own on the development storage (``TEST_S3_URL``), and a look inside it."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest
from aiobotocore.session import get_session

from penaria.integrations.s3.settings import S3Settings
from penaria.integrations.s3.storage import S3Storage, open_s3


@pytest.fixture(scope="session")
def s3_variables() -> Iterator[dict[str, Any]]:
    """``PENARIA_S3__*`` for a bucket made for this run and deleted after it."""
    url = os.environ.get("TEST_S3_URL")
    if not url:
        pytest.fail("TEST_S3_URL is not set: run `make dev-up` and the tests through `make test`")
    parts = urlsplit(url)
    variables = {
        "endpoint": f"{parts.scheme}://{parts.hostname}:{parts.port}",
        "bucket": f"penaria-test-{secrets.token_hex(6)}",
        "access_key_id": parts.username,
        "secret_access_key": parts.password,
    }
    settings = S3Settings.model_validate(variables)
    asyncio.run(_create(settings))
    yield variables
    asyncio.run(_delete(settings))


@pytest.fixture
async def storage(s3_variables: dict[str, Any]) -> AsyncIterator[S3Storage]:
    async with open_s3(S3Settings.model_validate(s3_variables)) as opened:
        yield opened


async def read(storage: S3Storage, key: str) -> bytes:
    stored = await storage.open(key)
    return b"".join([chunk async for chunk in stored.chunks()])


async def keys(storage: S3Storage, prefix: str = "") -> list[str]:
    return sorted(await storage.older_than(prefix, datetime.now(UTC) + timedelta(days=1)))


async def _create(settings: S3Settings) -> None:
    async with open_s3(settings) as storage:
        assert await storage.ensure_bucket() is True


async def _delete(settings: S3Settings) -> None:
    async with open_s3(settings) as storage:
        await storage.delete(await keys(storage))
    async with get_session().create_client(
        "s3",
        endpoint_url=str(settings.endpoint).rstrip("/"),
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key.get_secret_value(),
    ) as client:
        await client.delete_bucket(Bucket=settings.bucket)

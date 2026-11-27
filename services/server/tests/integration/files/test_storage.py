"""The S3 adapter against the development storage: what it leaves behind and how it reports failures."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from aiobotocore.session import get_session

from penaria.features.support.documents.domain.storage import ObjectMissingError, StorageUnavailableError
from penaria.integrations.s3 import storage as adapter
from penaria.integrations.s3.settings import S3Settings
from penaria.integrations.s3.storage import S3Storage, open_s3
from tests.integration.storage import keys, s3_variables, storage  # noqa: F401 - fixtures

pytestmark = pytest.mark.integration


async def unfinished(variables: dict[str, Any], key: str) -> int:
    """How many multipart uploads of the key are neither completed nor aborted."""
    async with get_session().create_client(
        "s3",
        endpoint_url=variables["endpoint"],
        region_name="us-east-1",
        aws_access_key_id=variables["access_key_id"],
        aws_secret_access_key=variables["secret_access_key"],
    ) as client:
        # SILO, as MinIO, lists the uploads of an exact key only.
        found = await client.list_multipart_uploads(Bucket=variables["bucket"], Prefix=key)
    return len(found.get("Uploads", []))


async def test_an_upload_that_stops_half_way_leaves_no_parts_behind(
    storage: S3Storage,  # noqa: F811 - the fixture
    s3_variables: dict[str, Any],  # noqa: F811 - the fixture
) -> None:
    counted = []

    async def interrupted() -> AsyncIterator[bytes]:
        yield b"x" * adapter.PART_BYTES
        yield b"x" * adapter.PART_BYTES
        counted.append(await unfinished(s3_variables, "incoming/half"))
        raise ConnectionResetError("the phone left the network")

    with pytest.raises(ConnectionResetError):
        await storage.put("incoming/half", interrupted(), content_type="application/octet-stream")

    assert counted == [1]
    assert await unfinished(s3_variables, "incoming/half") == 0
    assert await keys(storage, "incoming/half") == []


async def test_a_missing_object_is_told_apart_from_a_storage_that_fails(
    storage: S3Storage,  # noqa: F811 - the fixture
) -> None:
    with pytest.raises(ObjectMissingError):
        await storage.open("files/none/original")


async def test_a_storage_that_does_not_answer_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "ATTEMPTS", 1)
    # The discard port: nothing listens there.
    settings = S3Settings.model_validate(
        {"endpoint": "http://127.0.0.1:9", "bucket": "penaria", "access_key_id": "a", "secret_access_key": "b"}
    )

    async def content() -> AsyncIterator[bytes]:
        yield b"data"

    async with open_s3(settings) as unreachable:
        with pytest.raises(StorageUnavailableError):
            await unreachable.download("incoming/x", tmp_path / "x")
        with pytest.raises(StorageUnavailableError):
            await unreachable.put("incoming/x", content(), content_type="text/plain")
        with pytest.raises(StorageUnavailableError):
            await unreachable.delete(["incoming/x"])

"""The documents' ``ObjectStorage`` on S3."""

import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import BotoCoreError, ClientError

from penaria.features.support.documents.domain.storage import (
    ByteRange,
    ObjectMissingError,
    ObjectStorage,
    StorageUnavailableError,
    StoredObject,
)
from penaria.integrations.s3.settings import S3Settings

if TYPE_CHECKING:
    from aiobotocore.response import StreamingBody
    from types_aiobotocore_s3 import S3Client
    from types_aiobotocore_s3.type_defs import CompletedPartTypeDef

# The smallest part S3 takes but the last; an upload holds one in memory at a time.
PART_BYTES = 5 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 60
ATTEMPTS = 3
# A download holds a connection until its reader has it all; a page of thumbnails asks for many at once.
MAX_CONNECTIONS = 50
# The most keys one delete request takes.
DELETE_BATCH = 1000
MISSING_CODES = frozenset({"NoSuchKey", "404", "NotFound"})

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def open_s3(settings: S3Settings) -> AsyncIterator[S3Storage]:
    config = AioConfig(
        signature_version="s3v4",
        s3={"addressing_style": "path" if settings.path_style else "virtual"},
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=READ_TIMEOUT_SECONDS,
        retries={"max_attempts": ATTEMPTS, "mode": "standard"},
        max_pool_connections=MAX_CONNECTIONS,
        # Checksums only where S3 requires them: other implementations refuse the newer default ones.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    async with get_session().create_client(
        "s3",
        endpoint_url=None if settings.endpoint is None else str(settings.endpoint).rstrip("/"),
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key.get_secret_value(),
        config=config,
    ) as client:
        yield S3Storage(client, settings.bucket, settings.region)


class S3Storage(ObjectStorage):
    def __init__(self, client: S3Client, bucket: str, region: str) -> None:
        self._client = client
        self._bucket = bucket
        self._region = region

    async def ensure_bucket(self) -> bool:
        """Create the bucket if there is none; whether it was created."""
        with _reported("head_bucket"):
            try:
                await self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                if exc.response["Error"]["Code"] not in MISSING_CODES | {"NoSuchBucket"}:
                    raise
            else:
                return False
            # us-east-1 is the one region S3 refuses to be told.
            if self._region == "us-east-1":
                await self._client.create_bucket(Bucket=self._bucket)
            else:
                await self._client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region},  # type: ignore[typeddict-item]
                )
        return True

    async def put(self, key: str, chunks: AsyncIterator[bytes], *, content_type: str) -> None:
        """One request for what fits a part, a multipart upload for more."""
        buffer = bytearray()
        async for chunk in chunks:
            buffer += chunk
            if len(buffer) >= PART_BYTES:
                await self._put_in_parts(key, buffer, chunks, content_type)
                return
        with _reported("put_object"):
            await self._client.put_object(Bucket=self._bucket, Key=key, Body=bytes(buffer), ContentType=content_type)

    async def _put_in_parts(self, key: str, first: bytearray, rest: AsyncIterator[bytes], content_type: str) -> None:
        with _reported("create_multipart_upload"):
            started = await self._client.create_multipart_upload(Bucket=self._bucket, Key=key, ContentType=content_type)
        upload_id = started["UploadId"]
        parts: list[CompletedPartTypeDef] = []

        async def upload(body: bytes) -> None:
            number = len(parts) + 1
            with _reported("upload_part"):
                part = await self._client.upload_part(
                    Bucket=self._bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=body
                )
            parts.append({"PartNumber": number, "ETag": part["ETag"]})

        try:
            buffer = first
            async for chunk in rest:
                buffer += chunk
                if len(buffer) >= PART_BYTES:
                    await upload(bytes(buffer))
                    buffer = bytearray()
            if buffer:
                await upload(bytes(buffer))
            with _reported("complete_multipart_upload"):
                await self._client.complete_multipart_upload(
                    Bucket=self._bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
                )
        except BaseException:
            # The parts of an upload nobody completes take space until they are aborted. Should the abort
            # fail too, the storage expires them (a lifecycle rule on AWS, a day by itself on SILO).
            with contextlib.suppress(BotoCoreError, ClientError, OSError):
                await self._client.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
            raise

    async def put_file(self, key: str, path: Path, *, content_type: str) -> None:
        await self.put(key, _file_chunks(path), content_type=content_type)

    async def download(self, key: str, path: Path) -> None:
        stored = await self.open(key)
        with path.open("wb") as target:
            async for chunk in stored.chunks():
                target.write(chunk)

    async def open(self, key: str, byte_range: ByteRange | None = None) -> StoredObject:
        extra = {} if byte_range is None else {"Range": f"bytes={byte_range.first}-{byte_range.last}"}
        with _reported("get_object"):
            try:
                response = await self._client.get_object(Bucket=self._bucket, Key=key, **extra)  # type: ignore[arg-type]
            except ClientError as exc:
                if exc.response["Error"]["Code"] in MISSING_CODES:
                    raise ObjectMissingError(key) from exc
                raise
        return _S3Object(response["Body"], response["ContentLength"])

    async def delete(self, keys: list[str]) -> None:
        for start in range(0, len(keys), DELETE_BATCH):
            batch = keys[start : start + DELETE_BATCH]
            with _reported("delete_objects"):
                result = await self._client.delete_objects(
                    Bucket=self._bucket, Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True}
                )
            if errors := result.get("Errors"):
                logger.error("The storage did not delete %d objects: %s", len(errors), errors[0].get("Code"))
                raise StorageUnavailableError("the storage did not delete the files")

    async def older_than(self, prefix: str, before: datetime) -> list[str]:
        keys = []
        with _reported("list_objects"):
            async for page in self._client.get_paginator("list_objects_v2").paginate(
                Bucket=self._bucket, Prefix=prefix
            ):
                keys += [found["Key"] for found in page.get("Contents", []) if found["LastModified"] < before]
        return keys


class _S3Object:
    def __init__(self, body: StreamingBody, length: int) -> None:
        self._body = body
        self.length = length

    async def chunks(self) -> AsyncIterator[bytes]:
        async with self._body as body:
            with _reported("read_object"):
                while chunk := await body.read(CHUNK_BYTES):
                    yield chunk


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            yield chunk


@contextlib.contextmanager
def _reported(operation: str) -> Iterator[None]:
    """Turn the storage's failures into the one the features know, and say what failed in the log."""
    try:
        yield
    except (BotoCoreError, ClientError, TimeoutError, ConnectionError) as exc:
        logger.error("The storage failed on %s: %s", operation, exc)  # noqa: TRY400 - the message says it
        raise StorageUnavailableError("the file storage is not available; try again later") from exc

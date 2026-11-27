"""What the documents need from object storage, and the names of their objects."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from servicewright import ErrorKind, ServiceError

from penaria.features.shared.errors import ConflictError

# What was uploaded and is not cleaned yet: nothing serves it.
INCOMING_PREFIX = "incoming/"
# The longest side of each preview, in pixels.
SMALL_PREVIEW, LARGE_PREVIEW = 320, 1600
PREVIEW_SIZES = (SMALL_PREVIEW, LARGE_PREVIEW)
PREVIEW_TYPE = "image/webp"


class FilesOffError(ConflictError):
    """The install has no storage (``PENARIA_S3__*``), so it keeps no files."""

    code = "files_off"

    def __init__(self) -> None:
        super().__init__("this Penaria stores no files: its operator has not set up storage")


class StorageUnavailableError(ServiceError):
    """The storage did not answer or refused; the details are in the server's log."""

    kind = ErrorKind.UNAVAILABLE
    code = "storage_unavailable"


class ObjectMissingError(Exception):
    """The storage has no object under the key."""


@dataclass(frozen=True, slots=True)
class ByteRange:
    """Bytes ``first`` to ``last`` of an object, both included."""

    first: int
    last: int


class StoredObject(Protocol):
    # How many bytes ``chunks`` yields.
    length: int

    def chunks(self) -> AsyncIterator[bytes]:
        """The bytes, once; the connection is released when they end or the iteration is closed."""
        ...


class ObjectStorage(Protocol):
    async def put(self, key: str, chunks: AsyncIterator[bytes], *, content_type: str) -> None:
        """Store what ``chunks`` yields without holding it all; if it raises, nothing is stored."""
        ...

    async def put_file(self, key: str, path: Path, *, content_type: str) -> None: ...

    async def download(self, key: str, path: Path) -> None: ...

    async def open(self, key: str, byte_range: ByteRange | None = None) -> StoredObject: ...

    async def delete(self, keys: list[str]) -> None:
        """Delete the objects; a key without one is not an error."""
        ...

    async def older_than(self, prefix: str, before: datetime) -> list[str]:
        """The keys under ``prefix`` stored before ``before``."""
        ...


def incoming_key(file_id: UUID) -> str:
    return f"{INCOMING_PREFIX}{file_id}"


def original_key(file_id: UUID) -> str:
    return f"files/{file_id}/original"


def preview_key(file_id: UUID, size: int) -> str:
    return f"files/{file_id}/preview-{size}.webp"


def keys_of(file_id: UUID) -> list[str]:
    """Every object a file may have."""
    return [incoming_key(file_id), original_key(file_id), *(preview_key(file_id, size) for size in PREVIEW_SIZES)]

"""An install without storage: it keeps no files."""

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from penaria.features.support.documents.domain.storage import (
    ByteRange,
    FilesOffError,
    StoredObject,
)


class NoStorage:
    async def put(self, key: str, chunks: AsyncIterator[bytes], *, content_type: str) -> None:
        raise FilesOffError

    async def put_file(self, key: str, path: Path, *, content_type: str) -> None:
        raise FilesOffError

    async def download(self, key: str, path: Path) -> None:
        raise FilesOffError

    async def open(self, key: str, byte_range: ByteRange | None = None) -> StoredObject:
        raise FilesOffError

    async def delete(self, keys: list[str]) -> None:
        raise FilesOffError

    async def older_than(self, prefix: str, before: datetime) -> list[str]:
        raise FilesOffError

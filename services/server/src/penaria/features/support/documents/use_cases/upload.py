"""Taking a file in: it is streamed to storage as it arrives, where nothing serves it until the worker has
cleaned it (docs/design/documents.md, 4)."""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import InvalidError
from penaria.features.shared.ids import new_id
from penaria.features.shared.sights import Sight
from penaria.features.support.documents.domain.content import SNIFF_BYTES, sniff
from penaria.features.support.documents.domain.files import (
    File,
    FileKind,
    check_kind,
    clean_name,
    default_visibility,
)
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.domain.storage import FilesOffError, ObjectStorage, incoming_key
from penaria.features.support.documents.use_cases.access import (
    FileAccess,
    require_edit,
    require_not_archived,
    require_still_visible,
)
from penaria.features.support.documents.use_cases.events import file_event
from penaria.features.support.documents.use_cases.views import FileDetail

# Room for the multipart envelope around the file: a request longer than the limit and this is refused
# before its body is read.
ENVELOPE_ALLOWANCE = 1024 * 1024

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FilesConfig:
    """Whether the install keeps files, and how large one may be."""

    enabled: bool
    max_size: int

    def require_enabled(self) -> None:
        if not self.enabled:
            raise FilesOffError


class FileTooLargeError(InvalidError):
    code = "file_too_large"


class EmptyFileError(InvalidError):
    code = "empty_file"


class IncomingFile(Protocol):
    """A file as it arrives."""

    async def name(self) -> str:
        """The name the sender gives it; reads as little as it takes to know it."""
        ...

    def chunks(self) -> AsyncIterator[bytes]: ...


class UploadFile:
    def __init__(
        self,
        uow: AsyncUnitOfWork[DocumentsTransaction],
        access: FileAccess,
        storage: ObjectStorage,
        config: FilesConfig,
    ) -> None:
        self._uow = uow
        self._access = access
        self._storage = storage
        self._config = config

    async def execute(
        self, actor: Actor, entity_id: UUID, *, kind: FileKind, incoming: IncomingFile, declared_size: int | None
    ) -> FileDetail:
        """``declared_size`` is the length of the whole request, if the sender says it."""
        self._config.require_enabled()
        if declared_size is not None and declared_size > self._config.max_size + ENVELOPE_ALLOWANCE:
            raise self._too_large()
        # Everything that can be refused is refused before the body is read.
        await self._check_target(actor, entity_id, kind)
        name = clean_name(await incoming.name())
        file_id = new_id()
        media_type, size = await self._store(file_id, kind, incoming.chunks())
        try:
            return await self._record(
                actor, entity_id, file_id=file_id, kind=kind, name=name, media_type=media_type, size=size
            )
        except Exception:
            await self._storage.delete([incoming_key(file_id)])
            raise

    async def _check_target(self, actor: Actor, entity_id: UUID, kind: FileKind) -> Sight:
        sight = await self._access.entity(actor, entity_id)
        require_edit(sight)
        require_not_archived(sight)
        require_still_visible(kind, default_visibility(kind), [sight])
        return sight

    async def _store(self, file_id: UUID, kind: FileKind, chunks: AsyncIterator[bytes]) -> tuple[str, int]:
        """Stream the content to storage; return its media type, told from its start, and its size."""
        head = bytearray()
        async for chunk in chunks:
            head += chunk
            if len(head) >= SNIFF_BYTES:
                break
        if not head:
            raise EmptyFileError("the file is empty")
        media_type = sniff(bytes(head[:SNIFF_BYTES]))
        check_kind(kind, media_type)
        size = 0

        async def counted() -> AsyncIterator[bytes]:
            nonlocal size
            for_now = bytes(head)
            while True:
                size += len(for_now)
                if size > self._config.max_size:
                    raise self._too_large()
                yield for_now
                try:
                    for_now = await anext(chunks)
                except StopAsyncIteration:
                    return

        await self._storage.put(incoming_key(file_id), counted(), content_type=media_type)
        return media_type, size

    async def _record(
        self,
        actor: Actor,
        entity_id: UUID,
        *,
        file_id: UUID,
        kind: FileKind,
        name: str,
        media_type: str,
        size: int,
    ) -> FileDetail:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            # Again: a long upload leaves time for the access or the entity to change.
            sight = await self._check_target(actor, entity_id, kind)
            file = File.new(
                file_id=file_id,
                home_id=sight.home_id,
                kind=kind,
                name=name,
                media_type=media_type,
                size=size,
                added_by=actor.to_json(),
                now=now,
            )
            await tx.files.add(file)
            await tx.files.attach(file.id, entity_id)
            await tx.journal.append([file_event("file.added", actor, file, entity_id)])
            seen = await self._access.load(tx, actor, file.id, now)
        return FileDetail.of(seen)

    def _too_large(self) -> FileTooLargeError:
        return FileTooLargeError(
            f"a file is at most {self._config.max_size} bytes", params={"max_size": self._config.max_size}
        )

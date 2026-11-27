"""Reading files."""

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import NotFoundError
from penaria.features.support.documents.domain.files import (
    TRASH_RETENTION,
    Attachment,
    File,
    cover_of,
)
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.domain.storage import (
    PREVIEW_TYPE,
    ByteRange,
    ObjectMissingError,
    ObjectStorage,
    StoredObject,
    original_key,
    preview_key,
)
from penaria.features.support.documents.use_cases.access import FileAccess, kinds_to_add, may_edit
from penaria.features.support.documents.use_cases.views import EntityFile, EntityFiles, FileDetail, FileView

logger = logging.getLogger(__name__)


class PreviewNotFoundError(NotFoundError):
    code = "preview_not_found"


class ListEntityFiles:
    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID) -> EntityFiles:
        sight = await self._access.entity(actor, entity_id)
        # A guest reads a place on the way to what is meant for guests only by name.
        if not sight.contents:
            return EntityFiles(files=[], add_kinds=[])
        async with self._uow.query() as tx:
            attached = await tx.files.attached_to([entity_id])
            attachments = await tx.files.attachments_of([file.id for _, file in attached])
        seen = await self._access.see(actor, [file for _, file in attached], attachments)
        visible = [(attachment, one) for (attachment, _), one in zip(attached, seen, strict=True) if one.visible]
        cover = cover_of([(attachment, one.file) for attachment, one in visible])
        files = [
            EntityFile(
                view=FileView.of(one),
                is_cover=one.file.id == cover,
                can_detach=may_edit(sight),
                can_set_cover=may_edit(sight) and not sight.archived and one.file.is_ready_image,
            )
            for _, one in visible
        ]
        return EntityFiles(files=files, add_kinds=kinds_to_add(sight))


class FindCovers:
    """The covers of the entities a screen shows."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_ids: Collection[UUID]) -> dict[UUID, FileView]:
        """By entity id; an entity without a cover the actor sees, or not read by it, is left out."""
        async with self._uow.query() as tx:
            attached = await tx.files.attached_to(entity_ids)
            files = {file.id: file for _, file in attached if file.is_ready_image}
            attachments = await tx.files.attachments_of(files.keys())
        seen = {one.file.id: one for one in await self._access.see(actor, list(files.values()), attachments)}
        by_entity: dict[UUID, list[tuple[Attachment, File]]] = {}
        for attachment, file in attached:
            # A cover is a file the actor sees, on an entity whose contents it reads.
            one = seen.get(file.id)
            sight = None if one is None else one.sights.get(attachment.entity_id)
            if one is not None and one.visible and sight is not None and sight.contents:
                by_entity.setdefault(attachment.entity_id, []).append((attachment, file))
        return {
            entity_id: FileView.of(seen[cover])
            for entity_id, there in by_entity.items()
            if (cover := cover_of(there)) is not None
        }


class GetFile:
    def __init__(self, access: FileAccess) -> None:
        self._access = access

    async def execute(self, actor: Actor, file_id: UUID) -> FileDetail:
        return FileDetail.of(await self._access.read(actor, file_id, datetime.now(UTC)))


class ListTrash:
    """The home's removed files the actor may restore, the latest first."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, home_id: UUID) -> list[FileDetail]:
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            files = await tx.files.trash_of(home_id, now - TRASH_RETENTION)
            attachments = await tx.files.attachments_of([file.id for file in files])
        seen = await self._access.see(actor, files, attachments)
        return [FileDetail.of(one) for one in seen if one.readable(now)]


@dataclass(frozen=True, slots=True)
class Content:
    """One stored form of a file the actor may read: the original, or a preview."""

    file: File
    media_type: str
    # The longest side of a preview; None for the original.
    preview: int | None
    storage: ObjectStorage

    @property
    def etag(self) -> str:
        # The stored objects of a file never change once it is ready.
        suffix = "" if self.preview is None else f"-{self.preview}"
        return f'"{self.file.sha256}{suffix}"'

    async def open(self, byte_range: ByteRange | None = None) -> StoredObject:
        key = original_key(self.file.id) if self.preview is None else preview_key(self.file.id, self.preview)
        try:
            return await self.storage.open(key, byte_range)
        except ObjectMissingError as exc:
            logger.error("The storage has lost the object %s of file %s", key, self.file.id)  # noqa: TRY400
            raise ContentMissingError(
                "the file is no longer in storage", params={"file_id": str(self.file.id)}
            ) from exc


class ContentMissingError(NotFoundError):
    """The database knows the file and the storage lost it, as after a restore of only one of them."""

    code = "content_missing"


class ReadContent:
    def __init__(self, access: FileAccess, storage: ObjectStorage) -> None:
        self._access = access
        self._storage = storage

    async def original(self, actor: Actor, file_id: UUID) -> Content:
        file = await self._ready(actor, file_id)
        return Content(file=file, media_type=file.media_type, preview=None, storage=self._storage)

    async def preview(self, actor: Actor, file_id: UUID, size: int) -> Content:
        file = await self._ready(actor, file_id)
        if not file.previews:
            raise PreviewNotFoundError(params={"file_id": str(file_id)})
        return Content(file=file, media_type=PREVIEW_TYPE, preview=size, storage=self._storage)

    async def _ready(self, actor: Actor, file_id: UUID) -> File:
        file = (await self._access.read(actor, file_id, datetime.now(UTC))).file
        file.ensure_ready()
        return file

"""Reading files."""

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
    FileFailedError,
    FileNotReadyError,
    FileStatus,
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
            seen = await self._access.seen(tx, actor, [file for _, file in attached])
        visible = [(attachment, one) for (attachment, _), one in zip(attached, seen, strict=True) if one.visible]
        cover = cover_of([(attachment, one.file) for attachment, one in visible])
        files = [
            EntityFile(
                view=FileView.of(one),
                is_cover=one.file.id == cover,
                can_detach=may_edit(sight),
                can_set_cover=may_edit(sight) and not sight.archived and one.file.is_image,
            )
            for _, one in visible
        ]
        return EntityFiles(files=files, add_kinds=[kind.value for kind in kinds_to_add(sight)])


class FindCovers:
    """The covers of the entities a screen shows."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_ids: Collection[UUID]) -> dict[UUID, FileView]:
        """By entity id; an entity without a cover the actor sees, or not read by it, is left out."""
        async with self._uow.query() as tx:
            attached = await tx.files.attached_to(entity_ids)
            files = {file.id: file for _, file in attached if file.is_image}
            seen = {one.file.id: one for one in await self._access.seen(tx, actor, list(files.values()))}
        by_entity: dict[UUID, list[tuple[Attachment, File]]] = {}
        for attachment, file in attached:
            # What the actor does not see there, because the file or the entity's contents are not for it,
            # cannot be a cover for it.
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
    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, file_id: UUID) -> FileDetail:
        async with self._uow.query() as tx:
            seen = await self._access.load(tx, actor, file_id, datetime.now(UTC))
        return FileDetail.of(seen)


class ListTrash:
    """The home's removed files the actor may restore, the latest first."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, home_id: UUID) -> list[FileDetail]:
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            files = await tx.files.trash_of(home_id, now - TRASH_RETENTION)
            seen = await self._access.seen(tx, actor, files)
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
            raise ContentMissingError(f"file {self.file.id} has no object in storage", public=False) from exc


class ContentMissingError(NotFoundError):
    """The database knows the file and the storage lost it, as after a restore of only one of them."""

    code = "content_missing"


class ReadContent:
    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess, storage: ObjectStorage) -> None:
        self._uow = uow
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
        async with self._uow.query() as tx:
            file = (await self._access.load(tx, actor, file_id, datetime.now(UTC))).file
        if file.status is FileStatus.PROCESSING:
            raise FileNotReadyError(params={"file_id": str(file_id)})
        if file.status is FileStatus.FAILED:
            raise FileFailedError(params={"file_id": str(file_id)})
        return file

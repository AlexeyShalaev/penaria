"""The commands on files; each locks the file, checks access and writes the journal in its transaction."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.support.documents.domain.files import (
    CoverNotAnImageError,
    FileFailedError,
    FileKind,
    FileNotFoundInHomeError,
    FileNotReadyError,
    FileStatus,
    Visibility,
)
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.use_cases.access import (
    FileAccess,
    SeenFile,
    require_edit,
    require_editable,
    require_not_archived,
    require_still_visible,
)
from penaria.features.support.documents.use_cases.events import file_event
from penaria.features.support.documents.use_cases.views import FileDetail


class ChangeFile:
    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(
        self,
        actor: Actor,
        file_id: UUID,
        *,
        kind: FileKind | None = None,
        name: str | None = None,
        visibility: Visibility | None = None,
    ) -> FileDetail:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            seen = await self._access.load(tx, actor, file_id, now, for_update=True)
            require_editable(seen)
            changes = seen.file.change(kind=kind, name=name, visibility=visibility)
            if changes:
                require_still_visible(seen.file.kind, seen.file.visibility, seen.sights.values())
                await tx.files.save(seen.file)
                await tx.journal.append(
                    [file_event("file.changed", actor, seen.file, a.entity_id, changes) for a in seen.attachments]
                )
        return FileDetail.of(seen)


class RemoveFile:
    """Into the trash, where it stays for 30 days."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, file_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            seen = await self._access.load(tx, actor, file_id, now, for_update=True)
            require_editable(seen)
            await _to_trash(tx, actor, seen, now)


class RestoreFile:
    """Out of the trash, attached where it was."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, file_id: UUID) -> FileDetail:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            seen = await self._access.load(tx, actor, file_id, now, for_update=True)
            require_editable(seen)
            seen.file.restore(now)
            await tx.files.save(seen.file)
            await tx.journal.append(
                [file_event("file.restored", actor, seen.file, a.entity_id) for a in seen.attachments]
            )
        return FileDetail.of(seen)


class AttachFile:
    """One receipt or manual for one more thing: needs seeing the file and editing that thing."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, file_id: UUID) -> FileDetail:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            seen = await self._access.load(tx, actor, file_id, now, for_update=True)
            seen.file.ensure_not_removed()
            sight = await self._access.entity(actor, entity_id)
            if sight.home_id != seen.file.home_id:
                raise FileNotFoundInHomeError(params={"file_id": str(file_id)})
            require_edit(sight)
            require_not_archived(sight)
            if seen.attachment_to(entity_id) is None:
                await tx.files.attach(file_id, entity_id)
                await tx.journal.append([file_event("file.attached", actor, seen.file, entity_id)])
                seen = await self._access.load(tx, actor, file_id, now)
        return FileDetail.of(seen)


class DetachFile:
    """Detaching a file from its last entity removes it: it goes to the trash, still attached there."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, file_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            seen = await self._attached(tx, actor, entity_id, file_id, now)
            require_edit(seen.sights[entity_id])
            if len(seen.attachments) == 1:
                await _to_trash(tx, actor, seen, now)
            else:
                await tx.files.detach(file_id, entity_id)
                await tx.journal.append([file_event("file.detached", actor, seen.file, entity_id)])

    async def _attached(
        self, tx: DocumentsTransaction, actor: Actor, entity_id: UUID, file_id: UUID, now: datetime
    ) -> SeenFile:
        seen = await self._access.load(tx, actor, file_id, now, for_update=True)
        seen.file.ensure_not_removed()
        if seen.attachment_to(entity_id) is None or entity_id not in seen.sights:
            raise FileNotFoundInHomeError(params={"file_id": str(file_id)})
        return seen


class SetCover:
    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, file_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            seen = await self._access.load(tx, actor, file_id, now, for_update=True)
            seen.file.ensure_not_removed()
            attachment = seen.attachment_to(entity_id)
            sight = seen.sights.get(entity_id)
            if attachment is None or sight is None:
                raise FileNotFoundInHomeError(params={"file_id": str(file_id)})
            require_edit(sight)
            require_not_archived(sight)
            if seen.file.status is FileStatus.PROCESSING:
                raise FileNotReadyError(params={"file_id": str(file_id)})
            if seen.file.status is FileStatus.FAILED:
                raise FileFailedError(params={"file_id": str(file_id)})
            if not seen.file.is_image:
                raise CoverNotAnImageError("only an image can be a cover")
            if not attachment.is_cover:
                await tx.files.set_cover(file_id, entity_id)
                await tx.journal.append([file_event("file.cover_set", actor, seen.file, entity_id)])


async def _to_trash(tx: DocumentsTransaction, actor: Actor, seen: SeenFile, now: datetime) -> None:
    seen.file.remove(now)
    await tx.files.save(seen.file)
    await tx.files.clear_covers_of(seen.file.id)
    await tx.journal.append([file_event("file.removed", actor, seen.file, a.entity_id) for a in seen.attachments])

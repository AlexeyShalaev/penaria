"""How the documents apply access: a file is reached through its attachments (docs/design/documents.md, 6)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Permission, PermissionDeniedError
from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import ConflictError, NotFoundError
from penaria.features.shared.sights import EntitySights, Sight
from penaria.features.support.documents.domain.files import (
    Attachment,
    File,
    FileKind,
    FileNotFoundInHomeError,
    Visibility,
    default_visibility,
    permissions_to_see,
    shows_to,
)
from penaria.features.support.documents.domain.repositories import DocumentsTransaction


class AttachedEntityNotFoundError(NotFoundError):
    code = "entity_not_found"


class AttachedEntityArchivedError(ConflictError):
    code = "entity_archived"


@dataclass(frozen=True, slots=True)
class SeenFile:
    """A file, its attachments and what an actor may read of the entities that hold it."""

    file: File
    attachments: list[Attachment]
    # By entity id; the entities the actor may not read are left out.
    sights: dict[UUID, Sight]

    def visible_at(self, entity_id: UUID) -> bool:
        sight = self.sights.get(entity_id)
        return sight is not None and sight.contents and shows_to(self.file.kind, self.file.visibility, sight.access)

    @property
    def visible(self) -> bool:
        """One entity it is attached to is enough."""
        return any(self.visible_at(attachment.entity_id) for attachment in self.attachments)

    @property
    def editable(self) -> bool:
        """Changing or removing it takes editing every entity it is attached to."""
        return self.visible and all(may_edit(self.sights.get(a.entity_id)) for a in self.attachments)

    def readable(self, now: datetime) -> bool:
        """In the trash, only those who may restore it still find it."""
        if self.file.removed:
            return self.editable and not self.file.expired(now)
        return self.visible

    def attachment_to(self, entity_id: UUID) -> Attachment | None:
        return next((a for a in self.attachments if a.entity_id == entity_id), None)


class FileAccess:
    """Reading what an actor may see takes connections of its own (the sights port), so the reading use
    cases call these after their own query has closed: a page of thumbnails would otherwise hold two
    pooled connections each and could wait for itself."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], sights: EntitySights) -> None:
        self._uow = uow
        self._sights = sights

    async def see(
        self, actor: Actor, files: Sequence[File], attachments: dict[UUID, list[Attachment]]
    ) -> list[SeenFile]:
        """Each of the files with what the actor may read of where it is, in their order."""
        sights = await self._sights.sights(actor, {a.entity_id for there in attachments.values() for a in there})
        return [SeenFile(file, attachments.get(file.id, []), sights) for file in files]

    async def load(
        self,
        tx: DocumentsTransaction,
        actor: Actor,
        file_id: UUID,
        now: datetime,
        *,
        for_update: bool = False,
    ) -> SeenFile:
        """The file, for a command's transaction; anything the actor may not see reads as not found."""
        file = await tx.files.get(file_id, for_update=for_update)
        return await self._readable(actor, file_id, file, await tx.files.attachments_of([file_id]), now)

    async def read(self, actor: Actor, file_id: UUID, now: datetime) -> SeenFile:
        """The file, for reading it; anything the actor may not see reads as not found."""
        async with self._uow.query() as tx:
            file = await tx.files.get(file_id)
            attachments = await tx.files.attachments_of([file_id])
        return await self._readable(actor, file_id, file, attachments, now)

    async def entity(self, actor: Actor, entity_id: UUID) -> Sight:
        """The entity as the actor reads it."""
        sight = (await self._sights.sights(actor, [entity_id])).get(entity_id)
        if sight is None:
            raise AttachedEntityNotFoundError(params={"entity_id": str(entity_id)})
        return sight

    async def _readable(
        self,
        actor: Actor,
        file_id: UUID,
        file: File | None,
        attachments: dict[UUID, list[Attachment]],
        now: datetime,
    ) -> SeenFile:
        if file is not None:
            [seen] = await self.see(actor, [file], attachments)
            if seen.readable(now):
                return seen
        raise FileNotFoundInHomeError(params={"file_id": str(file_id)})


def may_edit(sight: Sight | None) -> bool:
    return sight is not None and sight.contents and sight.access.can(Permission.ENTITIES_EDIT)


def require_edit(sight: Sight) -> None:
    if not may_edit(sight):
        raise PermissionDeniedError(Permission.ENTITIES_EDIT)


def require_not_archived(sight: Sight) -> None:
    """An archived entity keeps its files, and gets no new ones."""
    if sight.archived:
        raise AttachedEntityArchivedError(params={"entity_id": str(sight.entity_id)})


def require_editable(seen: SeenFile) -> None:
    if not seen.editable:
        raise PermissionDeniedError(Permission.ENTITIES_EDIT, where=" on every place and thing the file is attached to")


def would_see(kind: FileKind, visibility: Visibility, sights: Iterable[Sight]) -> bool:
    """Whether the actor would see such a file attached to these entities."""
    return any(sight.contents and shows_to(kind, visibility, sight.access) for sight in sights)


def require_still_visible(kind: FileKind, visibility: Visibility, sights: Iterable[Sight]) -> None:
    """Refuse adding or changing a file so that the one who does it would no longer see it."""
    there: Sequence[Sight] = [sight for sight in sights if sight.contents]
    if would_see(kind, visibility, there):
        return
    missing = [
        permission
        for permission in permissions_to_see(kind, visibility)
        if not any(sight.access.can(permission) for sight in there)
    ]
    raise PermissionDeniedError(missing[0] if missing else Permission.ENTITIES_VIEW, where=" to see such a file")


def kinds_to_add(sight: Sight) -> list[FileKind]:
    """The kinds of file the actor may add to the entity: the ones ``require_still_visible`` accepts."""
    if sight.archived or not may_edit(sight):
        return []
    return [kind for kind in FileKind if would_see(kind, default_visibility(kind), [sight])]

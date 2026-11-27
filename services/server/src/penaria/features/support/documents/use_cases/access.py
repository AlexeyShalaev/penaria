"""How the documents apply access: a file is reached through its attachments (docs/design/documents.md, 6)."""

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

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
    def __init__(self, sights: EntitySights) -> None:
        self._sights = sights

    async def seen(self, tx: DocumentsTransaction, actor: Actor, files: Collection[File]) -> list[SeenFile]:
        """Each of the files with what the actor may read of where it is, in their order."""
        attachments = await tx.files.attachments_of([file.id for file in files])
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
        """The file; anything the actor may not see reads as not found."""
        file = await tx.files.get(file_id, for_update=for_update)
        if file is not None:
            [seen] = await self.seen(tx, actor, [file])
            if seen.readable(now):
                return seen
        raise FileNotFoundInHomeError(params={"file_id": str(file_id)})

    async def entity(self, actor: Actor, entity_id: UUID) -> Sight:
        """The entity as the actor reads it."""
        sight = (await self._sights.sights(actor, [entity_id])).get(entity_id)
        if sight is None:
            raise AttachedEntityNotFoundError(params={"entity_id": str(entity_id)})
        return sight


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


def require_still_visible(kind: FileKind, visibility: Visibility, sights: Iterable[Sight]) -> None:
    """Refuse adding or changing a file so that the one who does it would no longer see it."""
    there: Sequence[Sight] = [sight for sight in sights if sight.contents]
    if any(shows_to(kind, visibility, sight.access) for sight in there):
        return
    missing = [
        permission
        for permission in permissions_to_see(kind, visibility)
        if not any(sight.access.can(permission) for sight in there)
    ]
    raise PermissionDeniedError(missing[0] if missing else Permission.ENTITIES_VIEW, where=" to see such a file")


def kinds_to_add(sight: Sight) -> list[FileKind]:
    """The kinds of file the actor may add to the entity."""
    if sight.archived or not may_edit(sight):
        return []
    return [
        kind
        for kind in FileKind
        if all(sight.access.can(permission) for permission in permissions_to_see(kind, default_visibility(kind)))
    ]

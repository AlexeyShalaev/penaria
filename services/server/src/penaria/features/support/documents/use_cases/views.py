"""Files as an actor reads them, with what it may do with each."""

from dataclasses import dataclass
from uuid import UUID

from penaria.features.support.documents.domain.files import File
from penaria.features.support.documents.use_cases.access import SeenFile, may_edit


@dataclass(frozen=True, slots=True)
class FileView:
    file: File
    # Change its kind, name and visibility, remove it, or restore it from the trash.
    can_edit: bool

    @classmethod
    def of(cls, seen: SeenFile) -> FileView:
        return cls(file=seen.file, can_edit=seen.editable)


@dataclass(frozen=True, slots=True)
class Place:
    """An entity that holds a file, as far as the actor reads it."""

    entity_id: UUID
    names: tuple[str, ...]
    is_cover: bool
    can_detach: bool


@dataclass(frozen=True, slots=True)
class FileDetail:
    view: FileView
    # Only the entities whose contents the actor reads.
    places: list[Place]

    @classmethod
    def of(cls, seen: SeenFile) -> FileDetail:
        places = [
            Place(
                entity_id=attachment.entity_id,
                names=sight.names,
                is_cover=attachment.is_cover,
                can_detach=not seen.file.removed and may_edit(sight),
            )
            for attachment in seen.attachments
            if (sight := seen.sights.get(attachment.entity_id)) is not None and sight.contents
        ]
        return cls(view=FileView.of(seen), places=sorted(places, key=lambda place: (place.names, place.entity_id)))


@dataclass(frozen=True, slots=True)
class EntityFile:
    """A file in an entity's list."""

    view: FileView
    is_cover: bool
    can_detach: bool
    can_set_cover: bool


@dataclass(frozen=True, slots=True)
class EntityFiles:
    files: list[EntityFile]
    # The kinds the actor may add here; empty when it may add nothing.
    add_kinds: list[str]

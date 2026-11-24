"""What the registry use cases need from storage."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.shared.journal import Journal


@dataclass(frozen=True, slots=True)
class ChildrenFilter:
    include_archived: bool = False
    # Hide private entities (the reader lacks entities.view_private).
    hide_private: bool = True
    # Show only guest-visible entities and the places on the way to them.
    guest_view: bool = False


class EntityRepository(Protocol):
    async def get(self, entity_id: UUID, *, for_update: bool = False) -> Entity | None: ...

    async def get_many(self, entity_ids: Collection[UUID]) -> dict[UUID, Entity]:
        """The entities with these ids, by id."""
        ...

    async def ancestors(self, entity: Entity) -> list[Entity]:
        """The entities above ``entity``, from the root down."""
        ...

    async def add(self, entity: Entity) -> None: ...

    async def save(self, entity: Entity) -> None:
        """Write a changed entity; ``entity.version`` is already the new one."""
        ...

    async def children(self, home_id: UUID, parent_id: UUID | None, filter: ChildrenFilter) -> list[tuple[Entity, int]]:
        """The children of ``parent_id`` (the tops of the home for ``None``), by name, with their child counts."""
        ...

    async def has_guest_visible_below(self, entity: Entity) -> bool:
        """Whether a live, guest-visible entity sits somewhere below ``entity``."""
        ...

    async def subtree_height(self, entity: Entity) -> int:
        """How many levels the subtree has below ``entity``: 0 for a leaf."""
        ...

    async def move_descendants(self, old_path: Sequence[UUID], new_path: Sequence[UUID]) -> None:
        """Rewrite the paths below ``old_path`` to sit below ``new_path``."""
        ...


class RegistryTransaction(Protocol):
    @property
    def entities(self) -> EntityRepository: ...

    @property
    def journal(self) -> Journal: ...

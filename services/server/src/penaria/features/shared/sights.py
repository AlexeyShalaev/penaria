"""The port through which a feature learns what an actor may read of some entities, without reading the tree."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from penaria.features.shared.access import Access
from penaria.features.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class Sight:
    """An entity the actor may read, as it reads it."""

    entity_id: UUID
    home_id: UUID
    # The names along the path, the entity's own name last.
    names: tuple[str, ...]
    # What the actor may do at the entity.
    access: Access
    # False for a place a guest reads only by name, on the way to what is meant for guests.
    contents: bool
    archived: bool


class EntitySights(Protocol):
    async def sights(self, actor: Actor, entity_ids: Collection[UUID]) -> dict[UUID, Sight]:
        """The entities among these the actor may read, by id; the others, missing ones included, are left out."""
        ...

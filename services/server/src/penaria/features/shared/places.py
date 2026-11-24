"""The port through which a feature learns where a place of the home tree is, without reading the tree itself."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Place:
    id: UUID
    home_id: UUID
    # The ids from the top of the home down, the place's own id last.
    path: tuple[UUID, ...]
    # The names along the path, the place's own name last.
    names: tuple[str, ...]
    archived: bool


class PlaceDirectory(Protocol):
    async def find(self, entity_ids: Collection[UUID]) -> dict[UUID, Place]:
        """The places with these ids that exist, by id; it checks no access, so callers do."""
        ...

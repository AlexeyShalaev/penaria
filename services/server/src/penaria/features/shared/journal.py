"""The journal: an append-only record of what happened, written in the command's transaction."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from penaria.features.shared.actor import Actor
from penaria.features.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    home_id: UUID
    actor: Actor
    payload: dict[str, Any]
    entity_id: UUID | None = None
    version: int = 1
    id: UUID = field(default_factory=new_id)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    id: UUID
    type: str
    version: int
    home_id: UUID
    entity_id: UUID | None
    actor: dict[str, Any]
    payload: dict[str, Any]
    at: datetime


class Journal(Protocol):
    async def append(self, events: Sequence[Event]) -> None: ...

    async def for_entity(self, entity_id: UUID, *, limit: int) -> list[RecordedEvent]:
        """The entity's events, newest first."""
        ...

"""Reading the tree."""

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.repositories import RegistryTransaction
from penaria.features.core.registry.use_cases.access import (
    EntityAccess,
    EntityNotFoundError,
    as_seen,
    can_see,
    children_filter,
    load_readable,
    require,
)
from penaria.features.core.registry.use_cases.commands import PLACE_KEYS
from penaria.features.shared.access import Access, Permission, PermissionDeniedError
from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import RecordedEvent

HISTORY_LIMIT_MAX = 200


@dataclass(frozen=True, slots=True)
class EntityView:
    entity: Entity
    ancestors: list[Entity]
    access: Access
    children: int


class GetEntity:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID) -> EntityView:
        async with self._uow.query() as tx:
            entity, ancestors, access = await load_readable(tx, self._access, actor, entity_id)
            children = await tx.entities.children(
                entity.home_id, entity.id, children_filter(access, include_archived=False)
            )
        return EntityView(
            entity=as_seen(entity, access),
            ancestors=[as_seen(ancestor, access) for ancestor in ancestors],
            access=access,
            children=len(children),
        )


class ListChildren:
    """The children of a place, or the tops of the home (its properties) without one."""

    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(
        self, actor: Actor, *, home_id: UUID, parent_id: UUID | None, include_archived: bool = False
    ) -> list[tuple[Entity, int]]:
        async with self._uow.query() as tx:
            if parent_id is None:
                access = await self._access.at(actor, home_id, ())
                require(access, Permission.ENTITIES_VIEW)
            else:
                parent, _, access = await load_readable(tx, self._access, actor, parent_id)
                if parent.home_id != home_id:
                    raise EntityNotFoundError(params={"entity_id": str(parent_id)})
            children = await tx.entities.children(
                home_id, parent_id, children_filter(access, include_archived=include_archived)
            )
        return [(as_seen(child, access), count) for child, count in children]


class EntityHistory:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, *, limit: int = 50) -> list[RecordedEvent]:
        """The entity's events, newest first; places the actor may not see are left out of them."""
        async with self._uow.query() as tx:
            _, _, access = await load_readable(tx, self._access, actor, entity_id)
            # A guest is shown what is there, not how it got there.
            if access.guest_view:
                raise PermissionDeniedError(Permission.ENTITIES_VIEW, where=" beyond what is meant for guests")
            events = await tx.journal.for_entity(entity_id, limit=min(limit, HISTORY_LIMIT_MAX))
            hidden = await self._unseen_places(tx, actor, events)
        return [replace(event, payload=_without(event.payload, hidden)) for event in events]

    async def _unseen_places(self, tx: RegistryTransaction, actor: Actor, events: list[RecordedEvent]) -> set[str]:
        """The ids of the places the events name that the actor may not see where they are now, or that are gone.

        Each place is judged by the actor's access there, not at the entity: a grant over the kitchen
        does not show where in the house a thing came from.
        """
        named = {place["id"] for event in events for place in _places_in(event.payload)}
        entities = await tx.entities.get_many({UUID(place_id) for place_id in named})
        above = {step for entity in entities.values() for step in entity.path} - entities.keys()
        line = {**entities, **await tx.entities.get_many(above)}
        seen = set()
        for entity in entities.values():
            ancestors = [line[step] for step in entity.path[:-1] if step in line]
            if len(ancestors) == len(entity.path) - 1 and can_see(
                entity, ancestors, await self._access.at(actor, entity.home_id, entity.path)
            ):
                seen.add(str(entity.id))
        return named - seen


def _places_in(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [value for key in PLACE_KEYS if isinstance(value := payload.get(key), dict) and "id" in value]


def _without(payload: dict[str, Any], hidden: set[str]) -> dict[str, Any]:
    return {
        key: None if key in PLACE_KEYS and isinstance(value, dict) and value.get("id") in hidden else value
        for key, value in payload.items()
    }

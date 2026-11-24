"""Reading the tree."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.repositories import RegistryTransaction
from penaria.features.core.registry.use_cases.access import (
    EntityAccess,
    EntityNotFoundError,
    children_filter,
    load_readable,
    require,
)
from penaria.features.shared.access import Access, Permission
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
        return EntityView(entity=entity, ancestors=ancestors, access=access, children=len(children))


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
            return await tx.entities.children(
                home_id, parent_id, children_filter(access, include_archived=include_archived)
            )


class EntityHistory:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, *, limit: int = 50) -> list[RecordedEvent]:
        async with self._uow.query() as tx:
            await load_readable(tx, self._access, actor, entity_id)
            return await tx.journal.for_entity(entity_id, limit=min(limit, HISTORY_LIMIT_MAX))

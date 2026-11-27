"""The registry's side of the ``EntitySights`` port: what an actor may read of some entities."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.kinds import Privacy
from penaria.features.core.registry.domain.repositories import RegistryTransaction
from penaria.features.core.registry.use_cases.access import can_see
from penaria.features.shared.access import Access, AccessPolicy
from penaria.features.shared.actor import Actor
from penaria.features.shared.sights import Sight


class RegistrySights:
    """The same rules as reading an entity (access.py), for many at once."""

    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: AccessPolicy) -> None:
        self._uow = uow
        self._access = access

    async def sights(self, actor: Actor, entity_ids: Collection[UUID]) -> dict[UUID, Sight]:
        async with self._uow.query() as tx:
            entities = await tx.entities.get_many(entity_ids)
            above = {step for entity in entities.values() for step in entity.path} - entities.keys()
            line = {**entities, **await tx.entities.get_many(above)}
        accesses = await self._accesses(actor, list(entities.values()))
        seen = {
            entity.id: (entity, [line[step] for step in entity.path[:-1]], accesses[entity.id])
            for entity in entities.values()
            if can_see(entity, [line[step] for step in entity.path[:-1]], accesses[entity.id])
        }
        # A guest reads a place that is not meant for guests only by name, and only on the way to what is.
        by_name_only = {
            entity_id
            for entity_id, (entity, _, access) in seen.items()
            if access.guest_view and entity.privacy is not Privacy.GUEST_VISIBLE
        }
        on_the_way: set[UUID] = set()
        if by_name_only:
            async with self._uow.query() as tx:
                for entity_id in by_name_only:
                    if await tx.entities.has_guest_visible_below(seen[entity_id][0]):
                        on_the_way.add(entity_id)
        return {
            entity.id: Sight(
                entity_id=entity.id,
                home_id=entity.home_id,
                names=(*(ancestor.name for ancestor in ancestors), entity.name),
                access=access,
                contents=entity.id not in by_name_only,
                archived=entity.archived,
            )
            for entity, ancestors, access in seen.values()
            if entity.id not in by_name_only or entity.id in on_the_way
        }

    async def _accesses(self, actor: Actor, entities: list[Entity]) -> dict[UUID, Access]:
        by_home: dict[UUID, list[Entity]] = {}
        for entity in entities:
            by_home.setdefault(entity.home_id, []).append(entity)
        accesses: dict[UUID, Access] = {}
        for home_id, there in by_home.items():
            found = await self._access.accesses(actor, home_id, [entity.path for entity in there])
            accesses.update({entity.id: access for entity, access in zip(there, found, strict=True)})
        return accesses

"""The registry's side of the ``PlaceDirectory`` port: where places are and what they are called."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.core.registry.domain.repositories import RegistryTransaction
from penaria.features.shared.places import Place


class RegistryPlaces:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction]) -> None:
        self._uow = uow

    async def find(self, entity_ids: Collection[UUID]) -> dict[UUID, Place]:
        async with self._uow.query() as tx:
            entities = await tx.entities.get_many(entity_ids)
            above = {ancestor for entity in entities.values() for ancestor in entity.path[:-1]}
            names = {entity.id: entity.name for entity in entities.values()}
            names.update(
                {entity.id: entity.name for entity in (await tx.entities.get_many(above - names.keys())).values()}
            )
        return {
            entity.id: Place(
                id=entity.id,
                home_id=entity.home_id,
                path=entity.path,
                names=tuple(names[step] for step in entity.path),
                archived=entity.archived_at is not None,
            )
            for entity in entities.values()
        }

"""The commands that change the tree; each checks access and writes the journal in its transaction."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.kinds import ArchiveReason, Kind, Privacy, Status
from penaria.features.core.registry.domain.repositories import RegistryTransaction
from penaria.features.core.registry.use_cases.access import (
    EntityAccess,
    EntityNotFoundError,
    load_editable,
    require,
)
from penaria.features.shared.access import Permission
from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event


def _place(entity: Entity | None) -> dict[str, Any] | None:
    return None if entity is None else {"id": str(entity.id), "name": entity.name, "kind": entity.kind.value}


class CreateEntity:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(
        self,
        actor: Actor,
        *,
        home_id: UUID,
        kind: Kind,
        parent_id: UUID | None,
        name: str,
        aliases: Sequence[str] = (),
        quantity: Decimal | None = None,
        unit: str | None = None,
        privacy: Privacy = Privacy.NORMAL,
    ) -> Entity:
        async with self._uow.transaction() as tx:
            parent = None
            if parent_id is not None:
                parent = await load_editable(tx, self._access, actor, parent_id)
                if parent.home_id != home_id:
                    raise EntityNotFoundError(params={"entity_id": str(parent_id)})
            else:
                require(await self._access.at(actor, home_id, ()), Permission.ENTITIES_EDIT)
            entity = Entity.create(
                home_id=home_id,
                kind=kind,
                parent=parent,
                name=name,
                aliases=tuple(aliases),
                quantity=quantity,
                unit=unit,
                privacy=privacy,
            )
            await tx.entities.add(entity)
            await tx.journal.append(
                [
                    Event(
                        "entity.created",
                        home_id,
                        actor,
                        {"kind": kind.value, "name": entity.name, "parent": _place(parent)},
                        entity_id=entity.id,
                    )
                ]
            )
        return entity


class UpdateEntity:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(
        self,
        actor: Actor,
        entity_id: UUID,
        *,
        version: int | None,
        name: str | None = None,
        aliases: Sequence[str] | None = None,
        quantity: Decimal | None = None,
        clear_quantity: bool = False,
        unit: str | None = None,
        status: Status | None = None,
        privacy: Privacy | None = None,
    ) -> Entity:
        async with self._uow.transaction() as tx:
            entity = await load_editable(tx, self._access, actor, entity_id)
            entity.expect_version(version)
            changes = entity.update(
                name=name,
                aliases=tuple(aliases) if aliases is not None else None,
                quantity=quantity,
                clear_quantity=clear_quantity,
                unit=unit,
                status=status,
                privacy=privacy,
            )
            if changes:
                await tx.entities.save(entity)
                await tx.journal.append([Event("entity.updated", entity.home_id, actor, changes, entity_id=entity.id)])
        return entity


class MoveEntity:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, *, parent_id: UUID, version: int | None) -> Entity:
        async with self._uow.transaction() as tx:
            entity = await load_editable(tx, self._access, actor, entity_id)
            entity.expect_version(version)
            parent = await load_editable(tx, self._access, actor, parent_id)
            if parent.home_id != entity.home_id:
                raise EntityNotFoundError(params={"entity_id": str(parent_id)})
            old_parent = await tx.entities.get(entity.parent_id) if entity.parent_id else None
            old_path = entity.move_to(
                parent, subtree_height=await tx.entities.subtree_height(entity), by=actor.id, now=datetime.now(UTC)
            )
            await tx.entities.save(entity)
            await tx.entities.move_descendants(old_path, entity.path)
            await tx.journal.append(
                [
                    Event(
                        "entity.moved",
                        entity.home_id,
                        actor,
                        {"name": entity.name, "from": _place(old_parent), "to": _place(parent)},
                        entity_id=entity.id,
                    )
                ]
            )
        return entity


class ArchiveEntity:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, *, reason: ArchiveReason, version: int | None) -> Entity:
        async with self._uow.transaction() as tx:
            entity = await load_editable(tx, self._access, actor, entity_id)
            entity.expect_version(version)
            entity.archive(reason, datetime.now(UTC))
            await tx.entities.save(entity)
            await tx.journal.append(
                [
                    Event(
                        "entity.archived",
                        entity.home_id,
                        actor,
                        {"name": entity.name, "reason": reason.value},
                        entity_id=entity.id,
                    )
                ]
            )
        return entity


class RestoreEntity:
    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID, *, version: int | None) -> Entity:
        async with self._uow.transaction() as tx:
            entity = await load_editable(tx, self._access, actor, entity_id)
            entity.expect_version(version)
            entity.restore()
            await tx.entities.save(entity)
            await tx.journal.append(
                [Event("entity.restored", entity.home_id, actor, {"name": entity.name}, entity_id=entity.id)]
            )
        return entity


class VerifyEntity:
    """ "It is here": the place is confirmed now."""

    def __init__(self, uow: AsyncUnitOfWork[RegistryTransaction], access: EntityAccess) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, entity_id: UUID) -> Entity:
        async with self._uow.transaction() as tx:
            entity = await load_editable(tx, self._access, actor, entity_id)
            entity.verify(actor.id, datetime.now(UTC))
            await tx.entities.save(entity)
            await tx.journal.append(
                [Event("entity.verified", entity.home_id, actor, {"name": entity.name}, entity_id=entity.id)]
            )
        return entity

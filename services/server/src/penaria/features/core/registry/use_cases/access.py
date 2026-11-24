"""How the registry applies access: what an actor may see and change in the tree."""

import dataclasses
from collections.abc import Sequence
from uuid import UUID

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.kinds import Privacy
from penaria.features.core.registry.domain.repositories import ChildrenFilter, RegistryTransaction
from penaria.features.shared.access import Access, AccessPolicy, Permission, PermissionDeniedError
from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import NotFoundError


class EntityNotFoundError(NotFoundError):
    code = "entity_not_found"


class EntityAccess:
    def __init__(self, policy: AccessPolicy) -> None:
        self._policy = policy

    async def at(self, actor: Actor, home_id: UUID, path: Sequence[UUID]) -> Access:
        return await self._policy.access(actor, home_id, path)


async def load_readable(
    tx: RegistryTransaction, entity_access: EntityAccess, actor: Actor, entity_id: UUID, *, for_update: bool = False
) -> tuple[Entity, list[Entity], Access]:
    """The entity, its ancestors and the actor's access; anything the actor may not see reads as not found."""
    entity = await tx.entities.get(entity_id, for_update=for_update)
    if entity is None:
        raise EntityNotFoundError(params={"entity_id": str(entity_id)})
    ancestors = await tx.entities.ancestors(entity)
    access = await entity_access.at(actor, entity.home_id, entity.path)
    if not can_see(entity, ancestors, access):
        raise EntityNotFoundError(params={"entity_id": str(entity_id)})
    # A guest sees the places on the way to what is meant for guests (section 11.3).
    if (
        access.guest_view
        and entity.privacy is not Privacy.GUEST_VISIBLE
        and not await tx.entities.has_guest_visible_below(entity)
    ):
        raise EntityNotFoundError(params={"entity_id": str(entity_id)})
    return entity, ancestors, access


async def load_editable(tx: RegistryTransaction, entity_access: EntityAccess, actor: Actor, entity_id: UUID) -> Entity:
    """The entity, locked for the transaction, if the actor may change it."""
    entity, _, access = await load_readable(tx, entity_access, actor, entity_id, for_update=True)
    require(access, Permission.ENTITIES_EDIT)
    return entity


def can_see(entity: Entity, ancestors: Sequence[Entity], access: Access) -> bool:
    """Whether the permissions and the privacy flags let the actor see the entity at all."""
    if not access.can(Permission.ENTITIES_VIEW):
        return False
    line = (*ancestors, entity)
    return access.can(Permission.ENTITIES_VIEW_PRIVATE) or all(e.privacy is not Privacy.PRIVATE for e in line)


def as_seen(entity: Entity, access: Access) -> Entity:
    """The entity as the actor may read it: a guest learns only the name and kind of a place on the way
    to what is meant for guests (core-model.md, 11.3)."""
    if not access.guest_view or entity.privacy is Privacy.GUEST_VISIBLE:
        return entity
    return dataclasses.replace(entity, aliases=(), quantity=None, unit=None, verified_at=None, verified_by=None)


def children_filter(access: Access, *, include_archived: bool) -> ChildrenFilter:
    return ChildrenFilter(
        include_archived=include_archived,
        hide_private=not access.can(Permission.ENTITIES_VIEW_PRIVATE),
        guest_view=access.guest_view,
    )


def require(access: Access, permission: Permission) -> None:
    if not access.can(permission):
        raise PermissionDeniedError(permission)

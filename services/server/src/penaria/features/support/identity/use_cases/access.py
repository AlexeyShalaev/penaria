"""The access check every feature asks through the shared ``AccessPolicy`` port."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Access
from penaria.features.shared.actor import Actor
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.use_cases.homes import principal_of


class GrantAccessPolicy:
    """The union of the roles of the actor's active grants that cover the place."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def access(self, actor: Actor, home_id: UUID, path: Sequence[UUID]) -> Access:
        principal_type, principal_id = principal_of(actor)
        async with self._uow.query() as tx:
            roles = await tx.grants.applicable(principal_type, principal_id, home_id, path, datetime.now(UTC))
        if not roles:
            return Access(permissions=frozenset())
        owner = any(role.is_owner for role in roles)
        everything = owner or any(role.all_permissions for role in roles)
        permissions = frozenset().union(*(role.permissions for role in roles))
        return Access(
            permissions=permissions,
            owner=owner,
            all_permissions=everything,
            guest_view=all(role.guest_view for role in roles),
        )

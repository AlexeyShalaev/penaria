"""The access check every feature asks through the shared ``AccessPolicy`` port."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Access
from penaria.features.shared.actor import Actor
from penaria.features.support.identity.domain.models import access_of
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.use_cases.homes import principal_of


class GrantAccessPolicy:
    """The union of the roles of the actor's active grants that cover the place."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def access(self, actor: Actor, home_id: UUID, path: Sequence[UUID]) -> Access:
        [access] = await self.accesses(actor, home_id, [path])
        return access

    async def accesses(self, actor: Actor, home_id: UUID, paths: Sequence[Sequence[UUID]]) -> list[Access]:
        principal_type, principal_id = principal_of(actor)
        async with self._uow.query() as tx:
            scoped = await tx.grants.scoped_roles(principal_type, principal_id, home_id, datetime.now(UTC))
        # A grant covers a place when it is for the whole home or for the place or one above it.
        return [access_of([role for scope, role in scoped if scope is None or scope in path]) for path in paths]

"""Creating and reading homes."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Access, AccessPolicy
from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import NotFoundError
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, preset_roles
from penaria.features.support.identity.domain.permissions import Preset
from penaria.features.support.identity.domain.repositories import IdentityTransaction


class HomeNotFoundError(NotFoundError):
    code = "home_not_found"


def principal_of(actor: Actor) -> tuple[PrincipalType, UUID]:
    return PrincipalType(actor.kind.value), actor.id


class CreateHome:
    """A new home with its preset roles, and its creator as the owner."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, actor: Actor, *, name: str, timezone: str, locale: str) -> Home:
        home = Home.create(name=name, timezone=timezone, locale=locale)
        roles = preset_roles(home.id)
        principal_type, principal_id = principal_of(actor)
        owner = Grant(
            home_id=home.id,
            principal_type=principal_type,
            principal_id=principal_id,
            role_id=roles[Preset.OWNER].id,
        )
        async with self._uow.transaction() as tx:
            await tx.homes.add(home)
            await tx.roles.add_all(list(roles.values()))
            await tx.grants.add(owner)
            await tx.journal.append(
                [
                    Event("home.created", home.id, actor, {"name": home.name, "timezone": home.timezone}),
                    Event(
                        "grant.created",
                        home.id,
                        actor,
                        {"grant_id": str(owner.id), "principal_id": str(principal_id), "role": Preset.OWNER.value},
                    ),
                ]
            )
        return home


class ListHomes:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, actor: Actor) -> list[Home]:
        principal_type, principal_id = principal_of(actor)
        async with self._uow.query() as tx:
            return await tx.homes.with_grants_for(principal_type, principal_id, datetime.now(UTC))


class GetHome:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], access: AccessPolicy) -> None:
        self._uow = uow
        self._access = access

    async def execute(self, actor: Actor, home_id: UUID) -> tuple[Home, Access]:
        """The home and what the actor may do at its top; a home without the actor's grants is not found."""
        access = await self._access.access(actor, home_id, ())
        async with self._uow.query() as tx:
            home = await tx.homes.get(home_id)
        if home is None or not await self._has_any_grant(actor, home_id):
            raise HomeNotFoundError(params={"home_id": str(home_id)})
        return home, access

    async def _has_any_grant(self, actor: Actor, home_id: UUID) -> bool:
        principal_type, principal_id = principal_of(actor)
        async with self._uow.query() as tx:
            homes = await tx.homes.with_grants_for(principal_type, principal_id, datetime.now(UTC))
        return any(home.id == home_id for home in homes)

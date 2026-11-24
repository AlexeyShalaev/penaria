"""A home's people: its roles, who holds which grant, and changing or taking back grants (core-model.md, 3 and 11)."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Access, AccessPolicy, Permission
from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import ForbiddenError
from penaria.features.shared.journal import Event
from penaria.features.shared.places import Place, PlaceDirectory
from penaria.features.support.identity.domain.members import (
    GrantNotFoundError,
    InvalidGrantError,
    LastOwnerError,
    OwnerGrantError,
    RoleNotFoundError,
    changed_expiry,
    check_can_give,
    grant_expiry,
)
from penaria.features.support.identity.domain.models import Grant, PrincipalType, Role, User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.homes import HomeNotFoundError, principal_of


@dataclass(frozen=True, slots=True)
class GrantView:
    grant: Grant
    role: Role
    # None for the whole home.
    scope: Place | None
    granted_by: User | None


@dataclass(frozen=True, slots=True)
class Member:
    user: User
    grants: list[GrantView]


@dataclass(frozen=True, slots=True)
class GrantChanges:
    """What to change in a grant; a field left unset keeps its value."""

    role_id: UUID | None = None
    change_scope: bool = False
    # With ``change_scope``: the new scope, None for the whole home.
    scope_entity_id: UUID | None = None
    change_expiry: bool = False
    # With ``change_expiry``: the new end, None for none.
    expires_at: datetime | None = None


class ListRoles:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, actor: Actor, home_id: UUID) -> list[Role]:
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, datetime.now(UTC))
            return await tx.roles.for_home(home_id)


class ListMembers:
    """The accounts with access to the home and their grants; for those who manage its people."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], access: AccessPolicy, places: PlaceDirectory) -> None:
        self._uow = uow
        self._access = access
        self._places = places

    async def execute(self, actor: Actor, home_id: UUID) -> list[Member]:
        now = datetime.now(UTC)
        await require_manager(self._uow, self._access, actor, home_id, now)
        async with self._uow.query() as tx:
            grants = await tx.grants.active_in(home_id, PrincipalType.USER, now)
            roles = await tx.roles.get_many({grant.role_id for grant in grants})
            users = await tx.users.get_many(
                {grant.principal_id for grant in grants} | {g.granted_by for g in grants if g.granted_by}
            )
        views = await grant_views(self._places, grants, roles, users)
        by_user: dict[UUID, list[GrantView]] = {}
        for view in views:
            by_user.setdefault(view.grant.principal_id, []).append(view)
        members = [Member(user=users[user_id], grants=user_grants) for user_id, user_grants in by_user.items()]
        return sorted(
            members, key=lambda m: (not any(v.role.is_owner for v in m.grants), m.user.display_name.casefold())
        )


class ChangeGrant:
    """A member's new role, place or end of access. Owners are made by invitation and never changed."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], access: AccessPolicy, places: PlaceDirectory) -> None:
        self._uow = uow
        self._access = access
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID, grant_id: UUID, changes: GrantChanges) -> Grant:
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            grant = await _active_grant(tx, home_id, grant_id, now)
            roles = await tx.roles.get_many({grant.role_id} | ({changes.role_id} if changes.role_id else set()))
        if grant.principal_type is not PrincipalType.USER:
            raise InvalidGrantError("a guest link's access is not changed: make a new link", params={"field": "grant"})
        role = roles[grant.role_id]
        new_role = role_in(roles, changes.role_id, home_id) if changes.role_id else role
        if role.is_owner or new_role.is_owner:
            raise OwnerGrantError("owners are made by invitation and leave by revocation; their access is not changed")
        scope_id = changes.scope_entity_id if changes.change_scope else grant.scope_entity_id
        places = await self._places.find({p for p in (grant.scope_entity_id, scope_id) if p is not None})
        new_scope = check_place(places, scope_id, home_id) if changes.change_scope else place_of(places, scope_id)
        check_can_give(await access_at(self._access, actor, home_id, place_of(places, grant.scope_entity_id)), role)
        check_can_give(await access_at(self._access, actor, home_id, new_scope), new_role)
        if changes.change_expiry:
            expires_at = changed_expiry(new_role, changes.expires_at, now)
        elif grant.expires_at is None:
            expires_at = grant_expiry(new_role, None, now, field="expires_at")
        else:
            expires_at = grant.expires_at
        before = grant_payload(grant, role)
        async with self._uow.transaction() as tx:
            await tx.homes.lock(home_id)
            # Taken back or changed by someone else meanwhile: they decided first.
            if await tx.grants.get(home_id, grant_id) != grant:
                raise GrantNotFoundError("this access was changed or taken back meanwhile; look again")
            grant.role_id = new_role.id
            grant.scope_entity_id = scope_id
            grant.expires_at = expires_at
            await tx.grants.save(grant)
            await tx.journal.append(
                [Event("grant.changed", home_id, actor, {**grant_payload(grant, new_role), "before": before})]
            )
        return grant


class RevokeGrant:
    """Take back a grant: a member's, or a guest link's, which ends its guests' sessions at once."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], access: AccessPolicy, places: PlaceDirectory) -> None:
        self._uow = uow
        self._access = access
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID, grant_id: UUID) -> None:
        now = datetime.now(UTC)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            grant = await _active_grant(tx, home_id, grant_id, now)
            role = (await tx.roles.get_many({grant.role_id}))[grant.role_id]
        own = grant.principal_type is PrincipalType.USER and grant.principal_id == current.user_id
        if not own:
            places = await self._places.find({grant.scope_entity_id} if grant.scope_entity_id else set())
            check_can_give(await access_at(self._access, actor, home_id, place_of(places, grant.scope_entity_id)), role)
        if role.is_owner:
            current.require_recent_sign_in(now)
        async with self._uow.transaction() as tx:
            await tx.homes.lock(home_id)
            if await tx.grants.get(home_id, grant_id) != grant:
                raise GrantNotFoundError("this access was changed or taken back meanwhile; look again")
            if role.is_owner:
                await check_owner_remains(tx, home_id, [grant.id])
            await revoke(tx, actor, grant, role, now, reason="left" if own else "revoked")


class LeaveHome:
    """The signed-in person gives up all their access to a home; the last owner cannot."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, home_id: UUID) -> None:
        now = datetime.now(UTC)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            mine = await require_member(tx, actor, home_id, now)
            roles = await tx.roles.get_many({grant.role_id for grant in mine})
        if any(roles[grant.role_id].is_owner for grant in mine):
            current.require_recent_sign_in(now)
        async with self._uow.transaction() as tx:
            await tx.homes.lock(home_id)
            mine = await tx.grants.active_of(home_id, PrincipalType.USER, current.user_id, now)
            roles = await tx.roles.get_many({grant.role_id for grant in mine})
            if any(roles[grant.role_id].is_owner for grant in mine):
                await check_owner_remains(tx, home_id, [grant.id for grant in mine])
            for grant in mine:
                await revoke(tx, actor, grant, roles[grant.role_id], now, reason="left")


async def require_member(tx: IdentityTransaction, actor: Actor, home_id: UUID, now: datetime) -> list[Grant]:
    """The actor's active grants in the home; a home where they hold none is not found."""
    principal_type, principal_id = principal_of(actor)
    grants = await tx.grants.active_of(home_id, principal_type, principal_id, now)
    if not grants:
        raise HomeNotFoundError(params={"home_id": str(home_id)})
    return grants


async def require_manager(
    uow: AsyncUnitOfWork[IdentityTransaction], access: AccessPolicy, actor: Actor, home_id: UUID, now: datetime
) -> None:
    """Refuse anyone who does not manage the people of the whole home."""
    async with uow.query() as tx:
        await require_member(tx, actor, home_id, now)
    if not (await access.access(actor, home_id, ())).can(Permission.MEMBERS_MANAGE):
        raise ForbiddenError(
            f"needs {Permission.MEMBERS_MANAGE.value} over the whole home",
            code="permission_denied",
            params={"permission": Permission.MEMBERS_MANAGE},
        )


async def access_at(policy: AccessPolicy, actor: Actor, home_id: UUID, place: Place | None) -> Access:
    return await policy.access(actor, home_id, () if place is None else place.path)


def check_place(places: dict[UUID, Place], scope_entity_id: UUID | None, home_id: UUID) -> Place | None:
    """The place a new grant is to cover: a live place of this home, or None for the whole home."""
    if scope_entity_id is None:
        return None
    place = places.get(scope_entity_id)
    if place is None or place.home_id != home_id or place.archived:
        raise InvalidGrantError("no such place in this home", params={"field": "scope_entity_id"})
    return place


async def check_owner_remains(tx: IdentityTransaction, home_id: UUID, leaving: Collection[UUID]) -> None:
    """Refuse taking back owner grants when no owner would be left; the home is locked."""
    if all(grant.id in leaving for grant in await tx.grants.owners(home_id)):
        raise LastOwnerError("a home needs at least one owner: make someone else an owner first")


async def revoke(
    tx: IdentityTransaction, actor: Actor, grant: Grant, role: Role, now: datetime, *, reason: str
) -> None:
    """Take the grant back and journal it; a guest link's token and sessions end with it."""
    await tx.grants.revoke([grant.id], now)
    if grant.principal_type is PrincipalType.LINK:
        await tx.tokens.revoke_for(PrincipalType.LINK, grant.principal_id, now)
        ended = await tx.sessions.revoke_for_grant(grant.id, now)
        payload = {"link_id": str(grant.principal_id), "grant_id": str(grant.id), "sessions_ended": len(ended)}
        await tx.journal.append([Event("guest_link.revoked", grant.home_id, actor, payload)])
        return
    await tx.journal.append(
        [Event("grant.revoked", grant.home_id, actor, {**grant_payload(grant, role), "reason": reason})]
    )


async def grant_views(
    places: PlaceDirectory, grants: Sequence[Grant], roles: dict[UUID, Role], users: dict[UUID, User]
) -> list[GrantView]:
    found = await places.find({grant.scope_entity_id for grant in grants if grant.scope_entity_id})
    return [
        GrantView(
            grant=grant,
            role=roles[grant.role_id],
            scope=place_of(found, grant.scope_entity_id),
            granted_by=users.get(grant.granted_by) if grant.granted_by else None,
        )
        for grant in grants
    ]


async def _active_grant(tx: IdentityTransaction, home_id: UUID, grant_id: UUID, now: datetime) -> Grant:
    grant = await tx.grants.get(home_id, grant_id)
    if grant is None or not grant.is_active(now):
        raise GrantNotFoundError(params={"grant_id": str(grant_id)})
    return grant


def role_in(roles: dict[UUID, Role], role_id: UUID, home_id: UUID) -> Role:
    role = roles.get(role_id)
    if role is None or role.home_id != home_id:
        raise RoleNotFoundError(params={"role_id": str(role_id)})
    return role


def place_of(places: dict[UUID, Place], scope_entity_id: UUID | None) -> Place | None:
    if scope_entity_id is None:
        return None
    place = places.get(scope_entity_id)
    if place is None:
        raise RuntimeError(f"the place ({scope_entity_id}) a grant covers does not exist")
    return place


def grant_payload(grant: Grant, role: Role) -> dict[str, Any]:
    return {
        "grant_id": str(grant.id),
        "principal_type": grant.principal_type.value,
        "principal_id": str(grant.principal_id),
        "role_id": str(role.id),
        "role": role.preset.value if role.preset else role.name,
        "scope_entity_id": None if grant.scope_entity_id is None else str(grant.scope_entity_id),
        "expires_at": None if grant.expires_at is None else grant.expires_at.isoformat(),
    }

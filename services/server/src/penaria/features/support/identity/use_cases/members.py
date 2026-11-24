"""A home's people: its roles, who holds which grant, and changing or taking back grants (core-model.md, 3 and 11).

Every change to a home's people locks the home's row and decides who may make it under that lock,
from the grants as the transaction sees them, so two changes at once never both pass on a right
that one of them takes away.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Access, Permission, PermissionDeniedError
from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import StaleVersionError
from penaria.features.shared.journal import Event
from penaria.features.shared.places import Place, PlaceDirectory
from penaria.features.support.identity.domain.members import (
    GrantNotFoundError,
    InvalidGrantError,
    LastOwnerError,
    OwnerGrantError,
    OwnGrantError,
    RevokeReason,
    RoleNotFoundError,
    can_give,
    changed_expiry,
    check_can_give,
    grant_expiry,
    grant_payload,
)
from penaria.features.support.identity.domain.models import Grant, PrincipalType, Role, User, access_of
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
    """The home's roles, for those who give access."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, home_id: UUID) -> list[Role]:
        async with self._uow.query() as tx:
            await require_member(tx, Actor.user(current.user_id), home_id, datetime.now(UTC))
            return await tx.roles.for_home(home_id)


class ListMembers:
    """The accounts with access to the home and their grants; for those who manage its people."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID) -> list[Member]:
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            await require_manager(tx, Actor.user(current.user_id), home_id, now)
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
    """A member's new role, place or end of access. Owners are made by invitation and never changed,
    and nobody changes their own access."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID, grant_id: UUID, changes: GrantChanges) -> Grant:
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            grant = await active_grant(tx, home_id, grant_id, now)
            roles = await tx.roles.get_many({grant.role_id} | ({changes.role_id} if changes.role_id else set()))
        if grant.principal_type is not PrincipalType.USER:
            raise InvalidGrantError("a guest link's access is not changed: make a new link", params={"field": "grant"})
        if grant.principal_id == current.user_id:
            raise OwnGrantError("you cannot change your own access: ask someone else who manages the home's people")
        role = roles[grant.role_id]
        new_role = role_in(roles, changes.role_id, home_id) if changes.role_id else role
        if role.is_owner or new_role.is_owner:
            raise OwnerGrantError("owners are made by invitation and leave by revocation; their access is not changed")
        scope_id = changes.scope_entity_id if changes.change_scope else grant.scope_entity_id
        places = await self._places.find({p for p in (grant.scope_entity_id, scope_id) if p is not None})
        scope = place_of(places, grant.scope_entity_id)
        new_scope = check_place(places, scope_id, home_id) if changes.change_scope else scope
        if changes.change_expiry:
            expires_at = changed_expiry(new_role, changes.expires_at, now)
        elif grant.expires_at is None:
            expires_at = grant_expiry(new_role, None, now, field="expires_at")
        else:
            expires_at = grant.expires_at
        before = grant_payload(grant, role)
        async with self._uow.transaction() as tx:
            await lock_unchanged(tx, grant)
            check_can_give(await access_in(tx, actor, home_id, scope, now), role)
            check_can_give(await access_in(tx, actor, home_id, new_scope, now), new_role)
            grant.role_id = new_role.id
            grant.scope_entity_id = scope_id
            grant.expires_at = expires_at
            await tx.grants.save(grant)
            await tx.journal.append(
                [Event("grant.changed", home_id, actor, {**grant_payload(grant, new_role), "before": before})]
            )
            await disarm_links_of(tx, self._places, grant.principal_id, home_id, actor, now)
        return grant


class RevokeGrant:
    """Take back a grant: a member's, or a guest link's, which ends its guests' sessions at once."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID, grant_id: UUID) -> None:
        now = datetime.now(UTC)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            grant = await active_grant(tx, home_id, grant_id, now)
            role = (await tx.roles.get_many({grant.role_id}))[grant.role_id]
        own = grant.principal_type is PrincipalType.USER and grant.principal_id == current.user_id
        if role.is_owner:
            current.require_recent_sign_in(now)
        scope = await place_for(self._places, grant.scope_entity_id)
        async with self._uow.transaction() as tx:
            await lock_unchanged(tx, grant)
            if not own:
                check_can_give(await access_in(tx, actor, home_id, scope, now), role)
            if role.is_owner:
                await check_owner_remains(tx, home_id, [grant.id])
            await revoke(tx, actor, grant, role, now, reason=RevokeReason.LEFT if own else RevokeReason.REVOKED)
            if grant.principal_type is PrincipalType.USER:
                await disarm_links_of(tx, self._places, grant.principal_id, home_id, actor, now)


class LeaveHome:
    """The signed-in person gives up all their access to a home; the last owner cannot."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

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
                await revoke(tx, actor, grant, roles[grant.role_id], now, reason=RevokeReason.LEFT)
            await disarm_links_of(tx, self._places, current.user_id, home_id, actor, now)


async def require_member(tx: IdentityTransaction, actor: Actor, home_id: UUID, now: datetime) -> list[Grant]:
    """The actor's active grants in the home; a home where they hold none is not found."""
    principal_type, principal_id = principal_of(actor)
    grants = await tx.grants.active_of(home_id, principal_type, principal_id, now)
    if not grants:
        raise HomeNotFoundError(params={"home_id": str(home_id)})
    return grants


async def require_manager(tx: IdentityTransaction, actor: Actor, home_id: UUID, now: datetime) -> None:
    """Refuse anyone who does not manage the people of the whole home."""
    await require_member(tx, actor, home_id, now)
    if not (await access_in(tx, actor, home_id, None, now)).can(Permission.MEMBERS_MANAGE):
        raise PermissionDeniedError(Permission.MEMBERS_MANAGE, where=" over the whole home")


async def access_in(tx: IdentityTransaction, actor: Actor, home_id: UUID, place: Place | None, now: datetime) -> Access:
    """What the actor may do at the place (None: the top of the home), as this transaction sees the grants."""
    principal_type, principal_id = principal_of(actor)
    path = () if place is None else place.path
    return access_of(await tx.grants.applicable(principal_type, principal_id, home_id, path, now))


async def lock_unchanged(tx: IdentityTransaction, grant: Grant) -> None:
    """Lock the grant's home for a change to its people, refusing if the grant changed since it was read."""
    await tx.homes.lock(grant.home_id)
    if await tx.grants.get(grant.home_id, grant.id) != grant:
        raise StaleVersionError("this access was changed or taken back meanwhile; look again")


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
    tx: IdentityTransaction, actor: Actor, grant: Grant, role: Role, now: datetime, *, reason: RevokeReason
) -> None:
    """Take the grant back and journal it; a guest link's token and sessions end with it."""
    await tx.grants.revoke([grant.id], now)
    if grant.principal_type is PrincipalType.LINK:
        await tx.tokens.revoke_for(PrincipalType.LINK, grant.principal_id, now)
        ended = await tx.sessions.revoke_for_grant(grant.id, now)
        payload = {
            "link_id": str(grant.principal_id),
            "grant_id": str(grant.id),
            "sessions_ended": len(ended),
            "reason": reason.value,
        }
        await tx.journal.append([Event("guest_link.revoked", grant.home_id, actor, payload)])
        return
    await tx.journal.append(
        [Event("grant.revoked", grant.home_id, actor, {**grant_payload(grant, role), "reason": reason.value})]
    )


async def disarm_links_of(
    tx: IdentityTransaction, places: PlaceDirectory, user_id: UUID, home_id: UUID, actor: Actor, now: datetime
) -> None:
    """End the guest links the user made that they could no longer make, once their access shrank.

    Pending invitations need no such sweep: accepting one checks its inviter again.
    """
    links = [link for link in await tx.grants.active_in(home_id, PrincipalType.LINK, now) if link.granted_by == user_id]
    if not links:
        return
    roles = await tx.roles.get_many({link.role_id for link in links})
    found = await places.find({link.scope_entity_id for link in links if link.scope_entity_id})
    giver = Actor.user(user_id)
    for link in links:
        role = roles[link.role_id]
        if not can_give(await access_in(tx, giver, home_id, place_of(found, link.scope_entity_id), now), role):
            await revoke(tx, actor, link, role, now, reason=RevokeReason.GIVER_LOST_ACCESS)


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


async def active_grant(tx: IdentityTransaction, home_id: UUID, grant_id: UUID, now: datetime) -> Grant:
    grant = await tx.grants.get(home_id, grant_id)
    if grant is None or not grant.is_active(now):
        raise GrantNotFoundError(params={"grant_id": str(grant_id)})
    return grant


def role_in(roles: dict[UUID, Role], role_id: UUID, home_id: UUID) -> Role:
    role = roles.get(role_id)
    if role is None or role.home_id != home_id:
        raise RoleNotFoundError(params={"role_id": str(role_id)})
    return role


async def place_for(places: PlaceDirectory, scope_entity_id: UUID | None) -> Place | None:
    """The place an existing grant or invitation covers; None for the whole home."""
    if scope_entity_id is None:
        return None
    return place_of(await places.find({scope_entity_id}), scope_entity_id)


def place_of(places: dict[UUID, Place], scope_entity_id: UUID | None) -> Place | None:
    if scope_entity_id is None:
        return None
    place = places.get(scope_entity_id)
    if place is None:
        raise RuntimeError(f"the place ({scope_entity_id}) a grant covers does not exist")
    return place

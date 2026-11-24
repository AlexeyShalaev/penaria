"""Guest links: a grant to a ``link`` principal that anyone with the link uses until it ends (sign-in.md, 6.2)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.shared.places import Place, PlaceDirectory
from penaria.features.support.identity.domain.members import (
    GuestLink,
    GuestLinkEndedError,
    GuestLinkNotFoundError,
    Token,
    check_can_give,
    grant_payload,
)
from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, Role, User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, GuestSession, Session, hash_token
from penaria.features.support.identity.use_cases.attempts import find_by_secret
from penaria.features.support.identity.use_cases.members import (
    access_in,
    check_place,
    place_for,
    place_of,
    require_manager,
    require_member,
    role_in,
)

# Guest sessions one link keeps open at once; opening it again beyond that ends the oldest. A visit is
# a handful of phones, so this only stops a loop from piling up sessions.
GUEST_SESSIONS_MAX = 50


@dataclass(frozen=True, slots=True)
class GuestLinkView:
    link: GuestLink
    role: Role
    scope: Place | None
    granted_by: User | None


@dataclass(frozen=True, slots=True)
class GuestView:
    """What a guest is told about their visit: whose home, until when, and where it starts."""

    home: Home
    name: str
    expires_at: datetime
    scope: Place | None


class CreateGuestLink:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(
        self,
        current: CurrentSession,
        home_id: UUID,
        *,
        name: str,
        role_id: UUID,
        scope_entity_id: UUID | None,
        expires_at: datetime | None,
    ) -> tuple[GuestLinkView, str]:
        """The link and the secret token of its address, shown only now."""
        now = datetime.now(UTC)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            role = role_in(await tx.roles.get_many({role_id}), role_id, home_id)
            creator = await tx.users.get(current.user_id)
        found = await self._places.find(set() if scope_entity_id is None else {scope_entity_id})
        scope = check_place(found, scope_entity_id, home_id)
        link, token = GuestLink.create(
            home_id=home_id,
            role=role,
            name=name,
            scope_entity_id=scope_entity_id,
            expires_at=expires_at,
            granted_by=current.user_id,
            now=now,
        )
        async with self._uow.transaction() as tx:
            # Under the lock that taking the creator's access back takes, so their links end with it.
            await tx.homes.lock(home_id)
            check_can_give(await access_in(tx, actor, home_id, scope, now), role)
            await tx.grants.add(link.grant)
            await tx.tokens.add(link.token)
            await tx.journal.append(
                [
                    Event(
                        "guest_link.created",
                        home_id,
                        actor,
                        {**grant_payload(link.grant, role), "link_id": str(link.id), "name": link.token.name},
                    )
                ]
            )
        return GuestLinkView(link=link, role=role, scope=scope, granted_by=creator), token


class ListGuestLinks:
    """The home's guest links that still open; for those who manage its people."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID) -> list[GuestLinkView]:
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            await require_manager(tx, Actor.user(current.user_id), home_id, now)
            links = await tx.tokens.links_in(home_id, now)
            roles = await tx.roles.get_many({link.grant.role_id for link in links})
            users = await tx.users.get_many({link.grant.granted_by for link in links if link.grant.granted_by})
        places = await self._places.find({link.grant.scope_entity_id for link in links if link.grant.scope_entity_id})
        return [
            GuestLinkView(
                link=link,
                role=roles[link.grant.role_id],
                scope=place_of(places, link.grant.scope_entity_id),
                granted_by=users.get(link.grant.granted_by) if link.grant.granted_by else None,
            )
            for link in links
        ]


class OpenGuestLink:
    """Exchange a guest link's token for a guest session; the link keeps working until it ends."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, token: str, client: Client, session_token: str | None) -> tuple[GuestView, str]:
        """What the guest sees of the visit, and the token of their session's cookie.

        ``session_token`` is the browser's cookie: a browser already on this visit keeps its session.
        """
        found = await find_by_secret(
            self._uow,
            client,
            lambda tx: _link_token(tx, token),
            GuestLinkNotFoundError("this guest link does not work: check it, or ask your hosts for a new one"),
        )
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            grant = _the_grant(await tx.grants.for_principal(PrincipalType.LINK, found.principal_id))
            if found.revoked_at is not None or not grant.is_active(now):
                raise GuestLinkEndedError("this guest link has ended: ask your hosts for a new one")
            if session_token is not None and await _visiting(tx, session_token, grant, now):
                return await guest_view(self._uow, self._places, grant, found.name), session_token
            session, new_token = Session.start_guest(grant.id, client, now)
            await tx.sessions.add(session)
            await tx.sessions.trim_for_grant(grant.id, GUEST_SESSIONS_MAX, now)
            await tx.tokens.used(found.id, now, client.ip)
            await tx.journal.append(
                [
                    Event(
                        "guest_link.opened",
                        grant.home_id,
                        Actor.link(grant.principal_id),
                        {"link_id": str(grant.principal_id), "session_id": str(session.id), "ip": client.ip},
                    )
                ]
            )
        return await guest_view(self._uow, self._places, grant, found.name), new_token


class GetGuestView:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, guest: GuestSession) -> GuestView:
        async with self._uow.query() as tx:
            grant = await tx.grants.get(guest.home_id, guest.grant_id)
            token = await tx.tokens.for_principal(PrincipalType.LINK, guest.link_id)
        if grant is None or token is None:
            raise RuntimeError(f"the guest link ({guest.link_id}) of an open guest session is gone")
        return await guest_view(self._uow, self._places, grant, token.name)


async def guest_view(
    uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory, grant: Grant, name: str
) -> GuestView:
    if grant.expires_at is None:
        raise RuntimeError(f"the guest link's grant ({grant.id}) has no end")
    async with uow.query() as tx:
        home = await tx.homes.get(grant.home_id)
    if home is None:
        raise RuntimeError(f"the home ({grant.home_id}) of a guest link does not exist")
    scope = await place_for(places, grant.scope_entity_id)
    return GuestView(home=home, name=name, expires_at=grant.expires_at, scope=scope)


async def _link_token(tx: IdentityTransaction, token: str) -> Token | None:
    found = await tx.tokens.by_token_hash(hash_token(token))
    return found if found is not None and found.principal_type is PrincipalType.LINK else None


async def _visiting(tx: IdentityTransaction, session_token: str, grant: Grant, now: datetime) -> bool:
    """Whether the browser's session is an open one of this very link."""
    found = await tx.sessions.by_token_hash(hash_token(session_token))
    return found is not None and found[0].grant_id == grant.id and found[0].is_active(now)


def _the_grant(grants: list[Grant]) -> Grant:
    if len(grants) != 1:
        raise RuntimeError(f"a guest link has {len(grants)} grants instead of one")
    return grants[0]

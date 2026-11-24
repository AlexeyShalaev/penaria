"""Invitations into a home: made by those who manage its people, accepted once by a person with an account,
or by someone who makes their account through it (sign-in.md, 6.1)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.shared.places import Place, PlaceDirectory
from penaria.features.support.identity.domain.accounts import (
    UsernameTakenError,
    check_display_name,
    check_locale,
    check_password,
    check_username,
)
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mail import MailKind
from penaria.features.support.identity.domain.mail_texts import Link, role_name
from penaria.features.support.identity.domain.mailbox import check_email
from penaria.features.support.identity.domain.members import (
    AlreadyGrantedError,
    Invitation,
    InvitationNotFoundError,
    InviterLostAccessError,
    OwnInvitationError,
    RevokeReason,
    can_give,
    check_can_give,
    grant_payload,
)
from penaria.features.support.identity.domain.models import Home, PrincipalType, Role, User
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, hash_token
from penaria.features.support.identity.domain.throttle import account_key, mail_sent_key
from penaria.features.support.identity.use_cases.attempts import count_attempt, find_by_secret
from penaria.features.support.identity.use_cases.members import (
    access_in,
    check_place,
    disarm_links_of,
    place_for,
    place_of,
    require_manager,
    require_member,
    revoke,
    role_in,
)
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.sessions import start_session


@dataclass(frozen=True, slots=True)
class InvitationView:
    invitation: Invitation
    role: Role
    scope: Place | None
    created_by: User
    # Where its link was mailed when it was made.
    emailed_to: str | None = None


@dataclass(frozen=True, slots=True)
class InvitationPreview:
    """What the person who opens an invitation's link sees before accepting it."""

    invitation: Invitation
    home: Home
    role: Role
    scope: Place | None
    inviter: User


class CreateInvitation:
    def __init__(
        self,
        uow: AsyncUnitOfWork[IdentityTransaction],
        places: PlaceDirectory,
        postman: Postman,
        links: PublicLinks,
    ) -> None:
        self._uow = uow
        self._places = places
        self._postman = postman
        self._links = links

    async def execute(
        self,
        current: CurrentSession,
        home_id: UUID,
        *,
        role_id: UUID,
        scope_entity_id: UUID | None,
        valid_days: int,
        grant_expires_at: datetime | None,
        leave_when_accepted: bool,
        email: str | None = None,
    ) -> tuple[InvitationView, str]:
        """The invitation and its link, shown only now; mailed to ``email`` when given."""
        recipient = None if email is None else check_email(email)
        now = datetime.now(UTC)
        if recipient is not None:
            async with self._uow.transaction() as tx:
                await count_attempt(tx, [mail_sent_key(current.user_id)], now)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            role = role_in(await tx.roles.get_many({role_id}), role_id, home_id)
            inviter = await tx.users.get(current.user_id)
        if inviter is None:
            raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
        # Making an owner, or handing over the home, is as sensitive as it gets (sign-in.md, 5).
        if role.is_owner:
            current.require_recent_sign_in(now)
        found = await self._places.find(set() if scope_entity_id is None else {scope_entity_id})
        scope = check_place(found, scope_entity_id, home_id)
        invitation, token = Invitation.create(
            home_id=home_id,
            role=role,
            created_by=current.user_id,
            scope_entity_id=scope_entity_id,
            valid_days=valid_days,
            grant_expires_at=grant_expires_at,
            leave_when_accepted=leave_when_accepted,
            now=now,
        )
        url = self._links.invitation(token)
        async with self._uow.transaction() as tx:
            check_can_give(await access_in(tx, actor, home_id, scope, now), role)
            await tx.invitations.add(invitation)
            await tx.journal.append([Event("invitation.created", home_id, actor, _payload(invitation, role))])
            if recipient is not None:
                await self._mail(tx, invitation, role, inviter, recipient, url, now)
        view = InvitationView(invitation=invitation, role=role, scope=scope, created_by=inviter, emailed_to=recipient)
        return view, url

    async def _mail(
        self,
        tx: IdentityTransaction,
        invitation: Invitation,
        role: Role,
        inviter: User,
        to: str,
        url: str,
        now: datetime,
    ) -> None:
        """Mail the invitation's link, in the home's language: the person invited has no account to say theirs."""
        home = await tx.homes.get(invitation.home_id)
        if home is None:
            raise RuntimeError(f"the home ({invitation.home_id}) of a new invitation does not exist")
        locale = home.locale
        await self._postman.queue(
            tx,
            MailKind.INVITATION,
            to=to,
            locale=locale,
            values={
                "inviter": inviter.display_name,
                "home": home.name,
                "role": role_name(role.preset, locale) if role.preset else (role.name or ""),
            },
            link=Link(url, invitation.expires_at - now),
            user_id=None,
            created_by=inviter.id,
        )


class ListInvitations:
    """The home's invitations that can still be accepted; for those who manage its people."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID) -> list[InvitationView]:
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            await require_manager(tx, Actor.user(current.user_id), home_id, now)
            invitations = await tx.invitations.pending_in(home_id, now)
            roles = await tx.roles.get_many({invitation.role_id for invitation in invitations})
            users = await tx.users.get_many({invitation.created_by for invitation in invitations})
        places = await self._places.find({i.scope_entity_id for i in invitations if i.scope_entity_id})
        return [
            InvitationView(
                invitation=invitation,
                role=roles[invitation.role_id],
                scope=place_of(places, invitation.scope_entity_id),
                created_by=users[invitation.created_by],
            )
            for invitation in invitations
        ]


class RevokeInvitation:
    """Take back an invitation before it is accepted: its creator, or whoever could have made it."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, home_id: UUID, invitation_id: UUID) -> None:
        now = datetime.now(UTC)
        actor = Actor.user(current.user_id)
        async with self._uow.query() as tx:
            await require_member(tx, actor, home_id, now)
            invitation = await tx.invitations.get(home_id, invitation_id)
            if invitation is None:
                raise InvitationNotFoundError(params={"invitation_id": str(invitation_id)})
            role = (await tx.roles.get_many({invitation.role_id}))[invitation.role_id]
        invitation.check_open(now)
        scope = await place_for(self._places, invitation.scope_entity_id)
        async with self._uow.transaction() as tx:
            invitation = await tx.invitations.get(home_id, invitation_id, for_update=True)
            if invitation is None:
                raise RuntimeError(f"the invitation ({invitation_id}) disappeared")
            if invitation.created_by != current.user_id:
                check_can_give(await access_in(tx, actor, home_id, scope, now), role)
            invitation.check_open(now)
            invitation.revoked_at = now
            await tx.invitations.save(invitation)
            await tx.journal.append(
                [Event("invitation.revoked", home_id, actor, {"invitation_id": str(invitation.id)})]
            )


class PreviewInvitation:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, token: str, client: Client) -> InvitationPreview:
        """Whose home the invitation opens, from whom and with which role; refused once it cannot be accepted."""
        invitation = await _open_invitation(self._uow, token, client)
        async with self._uow.query() as tx:
            home = await tx.homes.get(invitation.home_id)
            role = (await tx.roles.get_many({invitation.role_id}))[invitation.role_id]
            inviter = await tx.users.get(invitation.created_by)
        if home is None or inviter is None:
            raise RuntimeError(f"the home or the inviter of the invitation ({invitation.id}) does not exist")
        return InvitationPreview(
            invitation=invitation,
            home=home,
            role=role,
            scope=await place_for(self._places, invitation.scope_entity_id),
            inviter=inviter,
        )


class AcceptInvitation:
    """The signed-in person accepts an invitation: the grant is theirs, and the invitation is used up."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory) -> None:
        self._uow = uow
        self._places = places

    async def execute(self, current: CurrentSession, token: str, client: Client) -> Home:
        """The home the person now belongs to."""
        invitation = await _open_invitation(self._uow, token, client)
        scope = await place_for(self._places, invitation.scope_entity_id)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            invitation, home = await _lock(tx, token, scope, now)
            if invitation.created_by == current.user_id:
                raise OwnInvitationError("this is your own invitation: pass the link on to the person it is for")
            await _accept(tx, self._places, invitation, current.user_id, now)
        return home


class AcceptInvitationWithNewAccount:
    """Someone without an account makes one through an invitation, the only way besides the setup."""

    def __init__(
        self,
        uow: AsyncUnitOfWork[IdentityTransaction],
        places: PlaceDirectory,
        hasher: PasswordHasher,
    ) -> None:
        self._uow = uow
        self._places = places
        self._hasher = hasher

    async def execute(
        self, token: str, *, username: str, display_name: str, password: str, locale: str, client: Client
    ) -> tuple[User, Home, str]:
        """The new account, the home it now belongs to and its first session's token."""
        username = check_username(username)
        display_name = check_display_name(display_name)
        locale = check_locale(locale)
        check_password(password)
        invitation = await _open_invitation(self._uow, token, client)
        scope = await place_for(self._places, invitation.scope_entity_id)
        password_hash = await self._hasher.hash(password)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            # Two people choosing the same username at once take turns here.
            await tx.failures.lock([account_key(username)])
            if await tx.users.by_username(username) is not None:
                raise UsernameTakenError("this username is taken: choose another", params={"field": "username"})
            invitation, home = await _lock(tx, token, scope, now)
            user = User(display_name=display_name, locale=locale, username=username)
            await tx.users.add(user)
            await tx.passwords.set(user.id, password_hash, now)
            await tx.journal.append(
                [
                    Event(
                        "account.created",
                        None,
                        Actor.user(user.id),
                        {"user_id": str(user.id), "invitation_id": str(invitation.id)},
                    )
                ]
            )
            await _accept(tx, self._places, invitation, user.id, now)
            session_token = await start_session(tx, user, client, now)
        return user, home, session_token


async def _open_invitation(uow: AsyncUnitOfWork[IdentityTransaction], token: str, client: Client) -> Invitation:
    """The invitation of the token, if it can still be accepted."""
    invitation = await find_by_secret(
        uow,
        client,
        lambda tx: tx.invitations.by_token_hash(hash_token(token)),
        InvitationNotFoundError("this invitation link does not work: check it, or ask for a new one"),
    )
    invitation.check_open(datetime.now(UTC))
    return invitation


async def _lock(tx: IdentityTransaction, token: str, scope: Place | None, now: datetime) -> tuple[Invitation, Home]:
    """The invitation, locked so it is accepted once, and its home, locked as every change to its people;
    under the lock, the invitation gives only what its inviter may still give."""
    invitation = await tx.invitations.by_token_hash(hash_token(token), for_update=True)
    if invitation is None:
        raise RuntimeError("an invitation disappeared while it was accepted")
    invitation.check_open(now)
    home = await tx.homes.lock(invitation.home_id)
    if home is None:
        raise RuntimeError(f"the home ({invitation.home_id}) of an invitation does not exist")
    role = (await tx.roles.get_many({invitation.role_id}))[invitation.role_id]
    inviter = await access_in(tx, Actor.user(invitation.created_by), invitation.home_id, scope, now)
    if not can_give(inviter, role):
        raise InviterLostAccessError(
            "the person who invited you can no longer give this access: ask them for a new invitation"
        )
    return invitation, home


async def _accept(
    tx: IdentityTransaction, places: PlaceDirectory, invitation: Invitation, user_id: UUID, now: datetime
) -> None:
    """Give the user the invitation's grant and use it up; for a transfer, the inviter's ownership ends."""
    held = await tx.grants.active_of(invitation.home_id, PrincipalType.USER, user_id, now)
    if any(g.role_id == invitation.role_id and g.scope_entity_id == invitation.scope_entity_id for g in held):
        raise AlreadyGrantedError("you already have this access to this home")
    role = (await tx.roles.get_many({invitation.role_id}))[invitation.role_id]
    grant = invitation.grant_for(user_id)
    await tx.grants.add(grant)
    invitation.accepted_at = now
    invitation.accepted_by = user_id
    await tx.invitations.save(invitation)
    actor = Actor.user(user_id)
    await tx.journal.append(
        [
            Event(
                "invitation.accepted",
                invitation.home_id,
                actor,
                {"invitation_id": str(invitation.id), "user_id": str(user_id), "grant_id": str(grant.id)},
            ),
            Event(
                "grant.created",
                invitation.home_id,
                actor,
                {**grant_payload(grant, role), "invitation_id": str(invitation.id)},
            ),
        ]
    )
    if invitation.leave_when_accepted:
        inviter = Actor.user(invitation.created_by)
        for owner in await tx.grants.owners(invitation.home_id):
            if owner.principal_id == invitation.created_by:
                await revoke(tx, inviter, owner, role, now, reason=RevokeReason.TRANSFERRED)
        await disarm_links_of(tx, places, invitation.created_by, invitation.home_id, inviter, now)


def _payload(invitation: Invitation, role: Role) -> dict[str, object]:
    return {
        "invitation_id": str(invitation.id),
        "role_id": str(role.id),
        "role": role.preset.value if role.preset else role.name,
        "scope_entity_id": None if invitation.scope_entity_id is None else str(invitation.scope_entity_id),
        "expires_at": invitation.expires_at.isoformat(),
        "grant_expires_at": None if invitation.grant_expires_at is None else invitation.grant_expires_at.isoformat(),
        "leave_when_accepted": invitation.leave_when_accepted,
    }

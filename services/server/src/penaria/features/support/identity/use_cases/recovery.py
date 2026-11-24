"""Getting back into an account: a reset link by email, from a home's admin, or from the operator (sign-in.md, 8).

A reset sets a new password and ends every session of the account; its passkeys stay, and the reset
page lists them, so a passkey nobody recognises can be removed after signing in.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import NotFoundError
from penaria.features.shared.journal import Event
from penaria.features.shared.places import PlaceDirectory
from penaria.features.support.identity.domain.accounts import check_password, normalize_username
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mail import MailKind
from penaria.features.support.identity.domain.mail_texts import Link
from penaria.features.support.identity.domain.mailbox import InvalidEmailError, MailOffError, check_email
from penaria.features.support.identity.domain.members import can_give
from penaria.features.support.identity.domain.models import PrincipalType, User
from penaria.features.support.identity.domain.passkeys import Passkey
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.recovery import (
    EMAILED_RESET_LIFETIME,
    HANDED_RESET_LIFETIME,
    AccountLink,
    AccountLinkNotFoundError,
    LinkPurpose,
    ResetBy,
    ResetNotAllowedError,
)
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, hash_token
from penaria.features.support.identity.domain.throttle import account_key, recovery_keys
from penaria.features.support.identity.use_cases.attempts import count_attempt, find_by_secret
from penaria.features.support.identity.use_cases.members import access_in, place_of, require_manager
from penaria.features.support.identity.use_cases.postman import Postman


class AccountNotFoundError(NotFoundError):
    code = "account_not_found"


@dataclass(frozen=True, slots=True)
class ResetPreview:
    """What the reset page shows before the new password: whose account, and the passkeys a reset keeps."""

    user: User
    passkeys: list[Passkey]


@dataclass(frozen=True, slots=True)
class HandedLink:
    """A reset link to pass on by hand, shown once."""

    url: str
    expires_at: datetime
    user: User


class RequestPasswordReset:
    """ "Forgot password": a reset link to the account's confirmed email, valid for 30 minutes.

    The answer is the same whether or not the account exists, has an email or is disabled.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], postman: Postman, links: PublicLinks) -> None:
        self._uow = uow
        self._postman = postman
        self._links = links

    async def execute(self, login: str, client: Client) -> None:
        """``login`` is a username or a confirmed email address."""
        if not await self._postman.on():
            raise MailOffError("the install sends no email: ask an admin of your home for a reset link")
        named = normalize_username(login)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await count_attempt(tx, recovery_keys(client.ip, named), now)
        async with self._uow.transaction() as tx:
            user = await _account_of(tx, named)
            if user is None or user.disabled_at is not None or user.email is None or user.username is None:
                return
            link, token = await _new_reset_link(tx, user, EMAILED_RESET_LIFETIME, now, created_by=None)
            await self._postman.queue(
                tx,
                MailKind.PASSWORD_RESET,
                to=user.email,
                locale=user.locale,
                values={"name": user.display_name, "username": user.username},
                link=Link(self._links.password_reset(token), EMAILED_RESET_LIFETIME),
                user_id=user.id,
                created_by=None,
            )
            await tx.journal.append([_created(link, user, ResetBy.SELF, Actor.system(), home_id=None)])


class PreviewPasswordReset:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, token: str, client: Client) -> ResetPreview:
        link = await _open_link(self._uow, token, client)
        async with self._uow.query() as tx:
            user = await _enabled_user(tx, link.user_id)
            return ResetPreview(user=user, passkeys=await tx.passkeys.for_user(user.id))


class ResetPassword:
    """A new password through a reset link: every session of the account ends, its passkeys stay."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher, postman: Postman) -> None:
        self._uow = uow
        self._hasher = hasher
        self._postman = postman

    async def execute(self, token: str, new_password: str, client: Client) -> User:
        check_password(new_password)
        await _open_link(self._uow, token, client)
        password_hash = await self._hasher.hash(new_password)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            link = await tx.account_links.by_token_hash(hash_token(token), LinkPurpose.PASSWORD_RESET, for_update=True)
            if link is None:
                raise AccountLinkNotFoundError("this link does not work: ask for a new one")
            link.check_open(now)
            user = await _enabled_user(tx, link.user_id, lock=True)
            if user.username is None:
                raise RuntimeError(f"the user ({user.id}) of a reset link has no account")
            await tx.passwords.set(user.id, password_hash, now)
            ended = await tx.sessions.revoke_all(user.id, now)
            await tx.account_links.use(link.id, now)
            # The person proved they hold the account: earlier wrong passwords no longer make them wait.
            await tx.failures.clear(account_key(user.username))
            actor = Actor.user(user.id)
            await tx.journal.append(
                [
                    Event(
                        "account.password_reset",
                        None,
                        actor,
                        {"user_id": str(user.id), "link_id": str(link.id), "sessions_ended": len(ended)},
                    ),
                    *[
                        Event("session.revoked", None, actor, {"user_id": str(user.id), "session_id": str(s)})
                        for s in ended
                    ],
                ]
            )
            await self._postman.notify(
                tx, user, MailKind.PASSWORD_CHANGED, {"name": user.display_name, "username": user.username}
            )
        return user


class CreateResetLink:
    """A home's admin makes a reset link for a member, to pass on by hand; it works for 24 hours.

    It hands the member's account to whoever opens it, so the admin must be able to give every access
    the member holds, in this home and any other, and the member must not be an install admin unless
    the admin is one too.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], places: PlaceDirectory, links: PublicLinks) -> None:
        self._uow = uow
        self._places = places
        self._links = links

    async def execute(self, current: CurrentSession, home_id: UUID, user_id: UUID) -> HandedLink:
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        actor = Actor.user(current.user_id)
        if user_id == current.user_id:
            raise ResetNotAllowedError("change your own password on your account page")
        async with self._uow.query() as tx:
            await require_manager(tx, actor, home_id, now)
            grants = await tx.grants.for_principal(PrincipalType.USER, user_id)
        active = [grant for grant in grants if grant.is_active(now)]
        if not any(grant.home_id == home_id for grant in active):
            raise AccountNotFoundError("this person is not a member of the home", params={"user_id": str(user_id)})
        places = await self._places.find({g.scope_entity_id for g in active if g.scope_entity_id})
        async with self._uow.transaction() as tx:
            admin = await tx.users.get(current.user_id)
            user = await _enabled_user(tx, user_id, lock=True)
            if admin is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            if user.install_admin and not admin.install_admin:
                raise ResetNotAllowedError("this person is an admin of the install: only another one can reset them")
            roles = await tx.roles.get_many({grant.role_id for grant in active})
            for grant in active:
                access = await access_in(tx, actor, grant.home_id, place_of(places, grant.scope_entity_id), now)
                if not can_give(access, roles[grant.role_id]):
                    raise ResetNotAllowedError(
                        "this person has access you could not give, here or in another home: "
                        "they can reset their password by email, or ask someone who can"
                    )
            link, token = await _new_reset_link(tx, user, HANDED_RESET_LIFETIME, now, created_by=current.user_id)
            await tx.journal.append([_created(link, user, ResetBy.ADMIN, actor, home_id=home_id)])
        return HandedLink(url=self._links.password_reset(token), expires_at=link.expires_at, user=user)


class CreateOperatorResetLink:
    """The operator's reset link, from the command line: for the owner who is locked out (sign-in.md, 8)."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], links: PublicLinks) -> None:
        self._uow = uow
        self._links = links

    async def execute(self, username: str) -> HandedLink:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            user = await tx.users.by_username(normalize_username(username))
            if user is None:
                raise AccountNotFoundError(f"no account has the username {username!r}")
            if user.disabled_at is not None:
                raise AccountNotFoundError(f"the account {username!r} is disabled")
            link, token = await _new_reset_link(tx, user, HANDED_RESET_LIFETIME, now, created_by=None)
            await tx.journal.append([_created(link, user, ResetBy.OPERATOR, Actor.system(), home_id=None)])
        return HandedLink(url=self._links.password_reset(token), expires_at=link.expires_at, user=user)


async def _account_of(tx: IdentityTransaction, login: str) -> User | None:
    """The account a "forgot password" form names: by its confirmed email, or by its username."""
    if "@" not in login:
        return await tx.users.by_username(login)
    try:
        email = check_email(login)
    except InvalidEmailError:
        return None
    return await tx.users.by_email(email)


async def _new_reset_link(
    tx: IdentityTransaction, user: User, lifetime: timedelta, now: datetime, *, created_by: UUID | None
) -> tuple[AccountLink, str]:
    """A new reset link for the user; the ones they had and did not use stop working."""
    link, token = AccountLink.create(
        user_id=user.id, purpose=LinkPurpose.PASSWORD_RESET, lifetime=lifetime, now=now, created_by=created_by
    )
    await tx.account_links.forget_unused(user.id, LinkPurpose.PASSWORD_RESET)
    await tx.account_links.add(link)
    return link, token


async def _open_link(uow: AsyncUnitOfWork[IdentityTransaction], token: str, client: Client) -> AccountLink:
    """The reset link of the token, if it still works; guessing tokens is limited like other secret links."""
    link = await find_by_secret(
        uow,
        client,
        lambda tx: tx.account_links.by_token_hash(hash_token(token), LinkPurpose.PASSWORD_RESET),
        AccountLinkNotFoundError("this link does not work: check it, or ask for a new one"),
    )
    link.check_open(datetime.now(UTC))
    return link


async def _enabled_user(tx: IdentityTransaction, user_id: UUID, *, lock: bool = False) -> User:
    user = await (tx.users.get_for_update(user_id) if lock else tx.users.get(user_id))
    if user is None or user.disabled_at is not None:
        raise AccountLinkNotFoundError("this link does not work: the account is gone or disabled")
    return user


def _created(link: AccountLink, user: User, by: ResetBy, actor: Actor, *, home_id: UUID | None) -> Event:
    payload = {
        "user_id": str(user.id),
        "link_id": str(link.id),
        "by": by.value,
        "expires_at": link.expires_at.isoformat(),
    }
    return Event("account.reset_link_created", home_id, actor, payload)

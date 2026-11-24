"""The account's email: an address becomes the account's only once a link sent to it is opened (sign-in.md, 15).

Reset links go to it, so an address nobody confirmed would hand the account to whoever owns that
address; without outgoing mail an account has no email at all.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mail import MailKind
from penaria.features.support.identity.domain.mail_texts import Link
from penaria.features.support.identity.domain.mailbox import check_email
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.recovery import (
    EMAIL_VERIFICATION_LIFETIME,
    AccountLink,
    AccountLinkNotFoundError,
    EmailTakenError,
    LinkPurpose,
)
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, hash_token
from penaria.features.support.identity.use_cases.account import load_user
from penaria.features.support.identity.use_cases.attempts import count_attempt, find_by_secret
from penaria.features.support.identity.use_cases.postman import Postman


@dataclass(frozen=True, slots=True)
class PendingEmail:
    email: str
    expires_at: datetime


class RequestEmailChange:
    """Send a confirmation link to the address the person wants for their account."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], postman: Postman, links: PublicLinks) -> None:
        self._uow = uow
        self._postman = postman
        self._links = links

    async def execute(self, current: CurrentSession, email: str) -> PendingEmail:
        email = check_email(email)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            # Each request mails a stranger's address, maybe: a few an hour per account.
            await count_attempt(tx, [f"email:{current.user_id}"], now)
        async with self._uow.transaction() as tx:
            user = await load_user(tx, current)
            await _check_free(tx, user, email)
            link, token = AccountLink.create(
                user_id=user.id,
                purpose=LinkPurpose.EMAIL_VERIFICATION,
                lifetime=EMAIL_VERIFICATION_LIFETIME,
                now=now,
                email=email,
            )
            await tx.account_links.forget_unused(user.id, LinkPurpose.EMAIL_VERIFICATION)
            await tx.account_links.add(link)
            await self._postman.queue(
                tx,
                MailKind.EMAIL_VERIFICATION,
                to=email,
                locale=user.locale,
                values={"name": user.display_name, "email": email},
                link=Link(self._links.email_verification(token), EMAIL_VERIFICATION_LIFETIME),
                user_id=user.id,
                created_by=user.id,
            )
        return PendingEmail(email=email, expires_at=link.expires_at)


class ConfirmEmail:
    """The link from the confirmation email makes its address the account's; it needs no session."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, token: str, client: Client) -> User:
        await find_by_secret(
            self._uow,
            client,
            lambda tx: tx.account_links.by_token_hash(hash_token(token), LinkPurpose.EMAIL_VERIFICATION),
            AccountLinkNotFoundError("this link does not work: check it, or ask for a new one"),
        )
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            link = await tx.account_links.by_token_hash(
                hash_token(token), LinkPurpose.EMAIL_VERIFICATION, for_update=True
            )
            if link is None or link.email is None:
                raise AccountLinkNotFoundError("this link does not work: ask for a new one")
            link.check_open(now)
            user = await tx.users.get_for_update(link.user_id)
            if user is None or user.disabled_at is not None:
                raise AccountLinkNotFoundError("this link does not work: the account is gone or disabled")
            # Two accounts confirming one address at once take turns here.
            await tx.failures.lock([f"email:{link.email}"])
            await _check_free(tx, user, link.email)
            user.email = link.email
            await tx.users.save(user)
            await tx.account_links.use(link.id, now)
            await tx.journal.append(
                [
                    Event(
                        "account.email_changed",
                        None,
                        Actor.user(user.id),
                        {"user_id": str(user.id), "email": link.email, "link_id": str(link.id)},
                    )
                ]
            )
        return user


class RemoveEmail:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> User:
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            if user.email is not None:
                user.email = None
                await tx.users.save(user)
                await tx.journal.append(
                    [Event("account.email_removed", None, Actor.user(user.id), {"user_id": str(user.id)})]
                )
        return user


async def _check_free(tx: IdentityTransaction, user: User, email: str) -> None:
    owner = await tx.users.by_email(email)
    if owner is not None and owner.id != user.id:
        raise EmailTakenError("another account uses this address", params={"field": "email"})

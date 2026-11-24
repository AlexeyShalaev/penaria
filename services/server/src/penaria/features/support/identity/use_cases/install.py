"""The install's own settings, for its admins: the mailbox it sends email through and the log of that email
(sign-in.md, 3 and 9.1)."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.mail import (
    Attempt,
    LoggedMail,
    MailDeliveryError,
    MailKind,
    MailTransport,
)
from penaria.features.support.identity.domain.mailbox import (
    InstallAdminRequiredError,
    InvalidEmailError,
    MailboxFields,
    MailboxLockedError,
    MailboxSource,
    StoredMailbox,
    check_email,
)
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.account import load_user
from penaria.features.support.identity.use_cases.postman import Mailboxes, Postman

LOG_PAGE_MAX = 100


@dataclass(frozen=True, slots=True)
class MailboxView:
    """The mailbox as the settings show it: where it comes from, its fields and whether a password is set."""

    source: MailboxSource | None
    fields: MailboxFields | None
    password_set: bool


class MailboxHealth(StrEnum):
    OFF = "off"
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MailboxStatus:
    health: MailboxHealth
    error: str | None = None


class GetMailbox:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], mailboxes: Mailboxes) -> None:
        self._uow = uow
        self._mailboxes = mailboxes

    async def execute(self, current: CurrentSession) -> MailboxView:
        async with self._uow.query() as tx:
            await require_install_admin(tx, current)
            return await _view(tx, self._mailboxes)


class SaveMailbox:
    """Connect the install's mailbox, or change it; the password is kept unless a new one is given.

    Where email goes decides who receives reset links, so it needs a recent sign-in, like adding a
    sign-in method.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], mailboxes: Mailboxes) -> None:
        self._uow = uow
        self._mailboxes = mailboxes

    async def execute(self, current: CurrentSession, new: MailboxFields, password: str | None) -> MailboxView:
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        if self._mailboxes.locked:
            raise MailboxLockedError("PENARIA_MAIL__HOST is set: the mailbox comes from the environment")
        # Sealed before the transaction, so it stays short.
        sealed = self._mailboxes.seal_password(password) if password else None
        async with self._uow.transaction() as tx:
            await require_install_admin(tx, current)
            stored = await tx.install_settings.mailbox(for_update=True)
            if sealed is None and stored is not None:
                sealed = stored.sealed_password
            # Without a login the server is not signed in to, so no password is kept.
            if new.username is None:
                sealed = None
            password_changed = password is not None and password != "" and new.username is not None
            changed = _changed(None if stored is None else stored.fields, new)
            if changed or password_changed:
                await tx.install_settings.save_mailbox(StoredMailbox(new, sealed), current.user_id, now)
                await tx.journal.append(
                    [
                        Event(
                            "install.mailbox_saved",
                            None,
                            Actor.user(current.user_id),
                            {"changed": changed, "password_changed": password_changed},
                        )
                    ]
                )
            return await _view(tx, self._mailboxes)


class RemoveMailbox:
    """Turn the install's email off: links are passed on by hand again."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], mailboxes: Mailboxes) -> None:
        self._uow = uow
        self._mailboxes = mailboxes

    async def execute(self, current: CurrentSession) -> None:
        current.require_recent_sign_in(datetime.now(UTC))
        if self._mailboxes.locked:
            raise MailboxLockedError("PENARIA_MAIL__HOST is set: the mailbox comes from the environment")
        async with self._uow.transaction() as tx:
            await require_install_admin(tx, current)
            if await tx.install_settings.remove_mailbox():
                await tx.journal.append([Event("install.mailbox_removed", None, Actor.user(current.user_id), {})])


class SendTestMail:
    """A test email through the saved mailbox, to the admin's own address unless another is given."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], postman: Postman) -> None:
        self._uow = uow
        self._postman = postman

    async def execute(self, current: CurrentSession, to: str | None) -> Attempt:
        async with self._uow.query() as tx:
            admin = await require_install_admin(tx, current)
        recipient = check_email(to, field="to") if to else admin.email
        if recipient is None:
            raise InvalidEmailError(
                "your account has no email: type the address to send the test to", params={"field": "to"}
            )
        attempt = await self._postman.send_now(
            MailKind.TEST,
            to=recipient,
            locale=admin.locale,
            values={},
            user_id=admin.id if recipient == admin.email else None,
            by=admin.id,
        )
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [
                    Event(
                        "install.mail_tested",
                        None,
                        Actor.user(admin.id),
                        {"mail_id": str(attempt.mail_id), "sent": attempt.sent},
                    )
                ]
            )
        return attempt


class CheckMailbox:
    """Whether the install can reach its mailbox now: it connects and signs in, without sending."""

    def __init__(
        self, uow: AsyncUnitOfWork[IdentityTransaction], mailboxes: Mailboxes, transport: MailTransport
    ) -> None:
        self._uow = uow
        self._mailboxes = mailboxes
        self._transport = transport

    async def execute(self, current: CurrentSession) -> MailboxStatus:
        async with self._uow.query() as tx:
            await require_install_admin(tx, current)
            resolved = await self._mailboxes.resolve(tx)
        if resolved.problem is not None:
            return MailboxStatus(MailboxHealth.FAILED, resolved.problem.describe())
        if resolved.mailbox is None:
            return MailboxStatus(MailboxHealth.OFF)
        try:
            await self._transport.probe(resolved.mailbox)
        except MailDeliveryError as exc:
            return MailboxStatus(MailboxHealth.FAILED, exc.failure.describe())
        return MailboxStatus(MailboxHealth.OK)


class ListMail:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, *, before: UUID | None, limit: int) -> list[LoggedMail]:
        """The newest mails, ``limit`` of them, older than the mail ``before`` when given."""
        async with self._uow.query() as tx:
            await require_install_admin(tx, current)
            return await tx.mail.page(before, min(limit, LOG_PAGE_MAX))


class ResendMail:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], postman: Postman) -> None:
        self._uow = uow
        self._postman = postman

    async def execute(self, current: CurrentSession, mail_id: UUID) -> Attempt:
        async with self._uow.query() as tx:
            await require_install_admin(tx, current)
        attempt = await self._postman.resend(mail_id, current.user_id)
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [
                    Event(
                        "mail.resent",
                        None,
                        Actor.user(current.user_id),
                        {"mail_id": str(mail_id), "sent": attempt.sent},
                    )
                ]
            )
        return attempt


async def require_install_admin(tx: IdentityTransaction, current: CurrentSession) -> User:
    user = await load_user(tx, current)
    if not user.install_admin:
        raise InstallAdminRequiredError("only an admin of the install can do this")
    return user


async def _view(tx: IdentityTransaction, mailboxes: Mailboxes) -> MailboxView:
    operator = mailboxes.operator
    if operator is not None:
        return MailboxView(MailboxSource.ENVIRONMENT, operator.fields, password_set=operator.password is not None)
    stored = await tx.install_settings.mailbox()
    if stored is None:
        return MailboxView(None, None, password_set=False)
    return MailboxView(MailboxSource.INTERFACE, stored.fields, password_set=stored.sealed_password is not None)


def _changed(before: MailboxFields | None, after: MailboxFields) -> list[str]:
    """The names of the fields that differ; every field for a new mailbox."""
    old = {} if before is None else asdict(before)
    return [name for name, value in asdict(after).items() if before is None or old[name] != value]

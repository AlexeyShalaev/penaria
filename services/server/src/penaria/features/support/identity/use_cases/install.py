"""The install's own settings, for its admins: the mailbox it sends email through and the log of that email
(sign-in.md, 3 and 9.1)."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import assert_never
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.mail import (
    Attempt,
    LoggedMail,
    MailDeliveryError,
    MailTransport,
)
from penaria.features.support.identity.domain.mailbox import (
    InstallAdminRequiredError,
    InvalidEmailError,
    InvalidMailboxError,
    MailboxFields,
    MailboxLockedError,
    MailboxSource,
    MailSecurity,
    StoredMailbox,
    check_email,
)
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.account import load_user
from penaria.features.support.identity.use_cases.postman import (
    Mailboxes,
    MailboxReady,
    MailboxUnreadable,
    MailOff,
    Postman,
)


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
    sign-in method. The saved password is kept only for the server and login it was given for: sent to
    another one, it would reach whoever runs that server, so a changed connection needs it again.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], mailboxes: Mailboxes) -> None:
        self._uow = uow
        self._mailboxes = mailboxes

    async def execute(self, current: CurrentSession, new: MailboxFields, password: str | None) -> MailboxView:
        """``password`` None keeps the saved one."""
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        _check_not_locked(self._mailboxes)
        # Without a login the server is not signed in to, so no password is kept.
        password_changed = new.username is not None and password is not None
        # Sealed before the transaction, so it stays short.
        sealed_new = self._mailboxes.seal_password(password) if password_changed and password else None
        async with self._uow.transaction() as tx:
            await require_install_admin(tx, current)
            stored = await tx.install_settings.mailbox(for_update=True)
            sealed = sealed_new if password_changed else _kept_password(stored, new)
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
        _check_not_locked(self._mailboxes)
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
        attempt = await self._postman.send_test(
            to=recipient, locale=admin.locale, user_id=admin.id if recipient == admin.email else None, by=admin.id
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
            state = await self._mailboxes.resolve(tx)
        match state:
            case MailOff():
                return MailboxStatus(MailboxHealth.OFF)
            case MailboxUnreadable(failure=failure):
                return MailboxStatus(MailboxHealth.FAILED, failure.describe())
            case MailboxReady(mailbox=mailbox):
                pass
            case _:
                assert_never(state)
        try:
            await self._transport.probe(mailbox)
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
            return await tx.mail.page(before, limit)


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


def _check_not_locked(mailboxes: Mailboxes) -> None:
    if mailboxes.operator is not None:
        raise MailboxLockedError("PENARIA_MAIL__HOST is set: the mailbox comes from the environment")


def _kept_password(stored: StoredMailbox | None, new: MailboxFields) -> str | None:
    """The saved password, when the new fields still sign in to the server it was given for."""
    if stored is None or stored.sealed_password is None or new.username is None:
        return None
    if _connection(stored.fields) != _connection(new):
        raise InvalidMailboxError(
            "the server or the login changed: enter the password again", params={"field": "password"}
        )
    return stored.sealed_password


def _connection(fields: MailboxFields) -> tuple[str, int, MailSecurity, str | None]:
    """What the password is sent to: the server, how, and as whom."""
    return fields.host, fields.port, fields.security, fields.username


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

"""The one way email leaves the install (sign-in.md, 9.1 and 15).

Whatever sends a mail queues it with the Postman in the transaction of the change it is about, so a
reset link is mailed only if its link was made. The mail loop of the api process sends what is due;
a test and a resend are sent at once, since an admin waits for them. Each attempt is one row of the
mail log, and a temporary failure brings the mail back after 1, 5, 15 and 30 minutes.

A mail being sent is held by a lease: taking it moves its next attempt five minutes ahead, in a
transaction that skips rows other replicas hold, so several api replicas never take the same mail.
Mails are taken one at a time, so a slow server never keeps a mail past its lease.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mail import (
    LEASE,
    RETENTION,
    SENDABLE_FOR,
    Attempt,
    Content,
    Envelope,
    Failure,
    FailureReason,
    Mail,
    MailDeliveryError,
    MailExpiredError,
    MailKind,
    MailNotFoundError,
    MailQueuedError,
    MailState,
    MailTransport,
    after_attempt,
)
from penaria.features.support.identity.domain.mail_texts import Link, compose
from penaria.features.support.identity.domain.mailbox import (
    MAILBOX_SEAL,
    Mailbox,
    MailboxSource,
    MailOffError,
    OperatorMailbox,
)
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.secrets import SecretBox, SecretUnreadableError

# How many due mails one pass of the loop sends at most before it looks again.
BATCH = 20
SEALED_LOGIN_UNREADABLE = (
    "the saved SMTP password does not open with PENARIA_SECRET_KEY (was the key changed?): enter the password again"
)
CONTENT_UNREADABLE = "the mail does not open with PENARIA_SECRET_KEY (was the key changed?)"
# Failures of the mailbox rather than of one mail: the rest of the due mail waits for the next pass.
MAILBOX_FAILURES = frozenset(
    {
        FailureReason.AUTH,
        FailureReason.CONNECT,
        FailureReason.TIMEOUT,
        FailureReason.TLS,
        FailureReason.DISCONNECTED,
        FailureReason.MAIL_OFF,
    }
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MailOff:
    """The install has no mailbox."""


@dataclass(frozen=True, slots=True)
class MailboxReady:
    mailbox: Mailbox


@dataclass(frozen=True, slots=True)
class MailboxUnreadable:
    """A mailbox is saved, but its password does not open with the install's keys."""

    failure: Failure


type MailboxState = MailOff | MailboxReady | MailboxUnreadable


class Mailboxes:
    """Where the mailbox comes from: the operator's environment, as a whole, or what an admin saved."""

    def __init__(self, operator: OperatorMailbox, box: SecretBox) -> None:
        self._operator = operator
        self._box = box

    @property
    def operator(self) -> Mailbox | None:
        """The mailbox of ``PENARIA_MAIL__*``; with it, the interface cannot change the mailbox."""
        return self._operator.mailbox

    async def resolve(self, tx: IdentityTransaction) -> MailboxState:
        if self._operator.mailbox is not None:
            return MailboxReady(self._operator.mailbox)
        stored = await tx.install_settings.mailbox()
        if stored is None:
            return MailOff()
        try:
            password = None if stored.sealed_password is None else self.open_password(stored.sealed_password)
        except SecretUnreadableError as exc:
            logger.error("The saved SMTP password does not open: %s", exc)  # noqa: TRY400 - expected, no trace
            return MailboxUnreadable(Failure(FailureReason.UNREADABLE, text=SEALED_LOGIN_UNREADABLE))
        return MailboxReady(Mailbox(fields=stored.fields, password=password, source=MailboxSource.INTERFACE))

    def seal_password(self, password: str) -> str:
        return self._box.seal(password, bound_to=MAILBOX_SEAL)

    def open_password(self, sealed: str) -> str:
        return self._box.open(sealed, bound_to=MAILBOX_SEAL)


class Postman:
    def __init__(
        self,
        uow: AsyncUnitOfWork[IdentityTransaction],
        mailboxes: Mailboxes,
        transport: MailTransport,
        box: SecretBox,
        links: PublicLinks,
    ) -> None:
        self._uow = uow
        self._mailboxes = mailboxes
        self._transport = transport
        self._box = box
        self._links = links

    async def on(self) -> bool:
        """Whether the install sends mail; links go by hand when it does not."""
        async with self._uow.query() as tx:
            return await self._on(tx)

    async def queue(
        self,
        tx: IdentityTransaction,
        kind: MailKind,
        *,
        to: str,
        locale: str,
        values: dict[str, str],
        link: Link | None,
        user_id: UUID | None,
        created_by: UUID | None,
    ) -> Mail:
        """Queue a mail in ``tx``: the mail loop sends it once the transaction commits. Refused when mail is off."""
        if not await self._on(tx):
            raise MailOffError("the install sends no email: pass the link on by hand")
        now = datetime.now(UTC)
        content = compose(kind, locale, values, server=self._links.origin, link=link)
        mail = self._mail(kind, to, locale, content, link, user_id, created_by, now, next_attempt_at=now)
        await tx.mail.add(mail)
        return mail

    async def notify(
        self, tx: IdentityTransaction, user: User, kind: MailKind, values: dict[str, str] | None = None
    ) -> None:
        """Tell the account something at its confirmed address, when the install sends mail; the email names
        the person and the account, and ``values`` adds what else its words need."""
        if user.email is None or not await self._on(tx):
            return
        if user.username is None:
            raise RuntimeError(f"the user ({user.id}) has an email but no account")
        named = {"name": user.display_name, "username": user.username, **(values or {})}
        await self.queue(
            tx, kind, to=user.email, locale=user.locale, values=named, link=None, user_id=user.id, created_by=None
        )

    async def send_test(self, *, to: str, locale: str, user_id: UUID | None, by: UUID) -> Attempt:
        """Send a test email at once, and once: the admin waits for the result."""
        now = datetime.now(UTC)
        content = compose(MailKind.TEST, locale, {}, server=self._links.origin)
        async with self._uow.transaction() as tx:
            state = await self._mailboxes.resolve(tx)
            if isinstance(state, MailOff):
                raise MailOffError("the install sends no email: set up its mailbox first")
            # Held from the start, so the mail loop leaves it to this sender.
            mail = self._mail(MailKind.TEST, to, locale, content, None, user_id, by, now, next_attempt_at=now + LEASE)
            mail.attempts = 1
            await tx.mail.add(mail)
        return await self._send_held(mail, state, by)

    async def resend(self, mail_id: UUID, by: UUID) -> Attempt:
        """Send a mail again at once, while it can still be sent; its retries start over."""
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            mail = await tx.mail.get(mail_id, for_update=True)
            if mail is None:
                raise MailNotFoundError(params={"mail_id": str(mail_id)})
            if mail.state is MailState.QUEUED:
                raise MailQueuedError("this email is waiting for its next attempt already")
            if not mail.sendable(now):
                raise MailExpiredError("this email can no longer be sent: its link stopped working, or it is too old")
            state = await self._mailboxes.resolve(tx)
            if isinstance(state, MailOff):
                raise MailOffError("the install sends no email: set up its mailbox first")
            mail.state = MailState.QUEUED
            mail.attempts = 1
            mail.next_attempt_at = now + LEASE
            await tx.mail.save(mail)
        return await self._send_held(mail, state, by)

    async def deliver_due(self) -> bool:
        """Send the mails whose attempt is due, one at a time; whether more may be due.

        A failure of the mailbox itself (it cannot be reached or signed in to) ends the pass: the
        other mails would only fail the same way, so they wait for their next pass untouched.
        """
        for _ in range(BATCH):
            now = datetime.now(UTC)
            async with self._uow.transaction() as tx:
                claimed = await tx.mail.claim_due(now, now + LEASE, 1)
                state = await self._mailboxes.resolve(tx) if claimed else MailOff()
            if not claimed:
                return False
            mail = claimed[0]
            mail.attempts += 1
            attempt = await self._send_held(mail, state, by=None)
            if attempt.failure is not None and attempt.failure.reason in MAILBOX_FAILURES:
                return False
            if isinstance(state, MailboxUnreadable):
                return False
        return True

    async def sweep(self) -> None:
        """Forget what can no longer be sent: the bodies of stale mails, old log rows and expired links."""
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await tx.mail.forget_content(now)
            await tx.mail.delete_created_before(now - RETENTION)
            await tx.account_links.forget_expired(now)

    async def _on(self, tx: IdentityTransaction) -> bool:
        return not isinstance(await self._mailboxes.resolve(tx), MailOff)

    async def _send_held(self, mail: Mail, state: MailboxState, by: UUID | None) -> Attempt:
        """One attempt at a mail this sender holds, recorded with its outcome; ``mail.attempts`` counts it."""
        started = time.monotonic()
        failure, message_id = await self._attempt(mail, state)
        duration_ms = round((time.monotonic() - started) * 1000)
        now = datetime.now(UTC)
        mail.state, mail.next_attempt_at = after_attempt(mail, failure, now)
        attempt = Attempt(
            mail_id=mail.id,
            at=now,
            duration_ms=duration_ms,
            failure=failure,
            message_id=message_id,
            next_attempt_at=mail.next_attempt_at,
            by=by,
        )
        async with self._uow.transaction() as tx:
            await tx.mail.save(mail)
            await tx.mail.add_attempt(attempt)
        _log(mail, attempt)
        return attempt

    async def _attempt(self, mail: Mail, state: MailboxState) -> tuple[Failure | None, str | None]:
        if not mail.sendable(datetime.now(UTC)) or mail.sealed_content is None:
            return Failure(FailureReason.EXPIRED), None
        match state:
            case MailOff():
                return Failure(FailureReason.MAIL_OFF), None
            case MailboxUnreadable(failure=failure):
                return failure, None
            case MailboxReady(mailbox=mailbox):
                pass
        try:
            content = self._open(mail, mail.sealed_content)
        except SecretUnreadableError:
            return Failure(FailureReason.UNREADABLE, text=CONTENT_UNREADABLE), None
        try:
            message_id = await self._transport.send(mailbox, Envelope(to=mail.to_address, content=content))
        except MailDeliveryError as exc:
            return exc.failure, None
        return None, message_id

    def _mail(
        self,
        kind: MailKind,
        to: str,
        locale: str,
        content: Content,
        link: Link | None,
        user_id: UUID | None,
        created_by: UUID | None,
        now: datetime,
        *,
        next_attempt_at: datetime,
    ) -> Mail:
        mail = Mail(
            kind=kind,
            to_address=to,
            locale=locale,
            subject=content.subject,
            created_at=now,
            expires_at=now + (SENDABLE_FOR if link is None else link.valid_for),
            user_id=user_id,
            created_by=created_by,
            next_attempt_at=next_attempt_at,
        )
        mail.sealed_content = self._box.seal(_pack(content), bound_to=_binding(mail.id))
        return mail

    def _open(self, mail: Mail, sealed: str) -> Content:
        text, _, html = self._box.open(sealed, bound_to=_binding(mail.id)).partition(BODY_SEPARATOR)
        return Content(subject=mail.subject, text=text, html=html)


# The text part never holds a NUL character, so it separates the two parts.
BODY_SEPARATOR = "\x00"


def _pack(content: Content) -> str:
    return f"{content.text}{BODY_SEPARATOR}{content.html}"


def _binding(mail_id: UUID) -> str:
    """The record a mail's sealed body belongs to: copied into another mail, it does not open."""
    return f"mail/{mail_id}/content"


def _log(mail: Mail, attempt: Attempt) -> None:
    failure = attempt.failure
    if failure is None:
        logger.info("Mail %s (%s) sent, attempt %d", mail.id, mail.kind.value, mail.attempts)
        return
    # The server's words may name the recipient: the log keeps only the kind of failure; the mail log has the rest.
    logger.warning(
        "Mail %s (%s) not sent, attempt %d: %s, SMTP code %s; next attempt %s",
        mail.id,
        mail.kind.value,
        mail.attempts,
        failure.reason.value,
        failure.smtp_code,
        "none" if attempt.next_attempt_at is None else attempt.next_attempt_at.isoformat(),
    )

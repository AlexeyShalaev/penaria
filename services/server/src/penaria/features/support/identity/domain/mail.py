"""Emails the install sends: one queue in PostgreSQL, a log of every attempt, retries of temporary failures
(sign-in.md, 9.1 and 15)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from penaria.features.shared.errors import ConflictError, NotFoundError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.mailbox import Mailbox

# The pauses before the 2nd to the 5th attempt after a temporary failure.
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=30))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# A sender holds the mail it took this long before another replica may take it again.
LEASE = timedelta(minutes=5)
# A mail without a link can be sent again this long; one with a link, while the link works.
SENDABLE_FOR = timedelta(days=3)
# The log keeps a mail and its attempts this long.
RETENTION = timedelta(days=30)
SMTP_TEMPORARY = range(400, 500)


class MailKind(StrEnum):
    TEST = "test"
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105 - a kind of mail, not a password
    INVITATION = "invitation"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - a kind of mail, not a password
    PASSKEY_ADDED = "passkey_added"
    EMAIL_CHANGED = "email_changed"
    EMAIL_REMOVED = "email_removed"
    TOTP_ENABLED = "totp_enabled"
    TOTP_DISABLED = "totp_disabled"
    RECOVERY_CODE_USED = "recovery_code_used"
    RECOVERY_CODES_REGENERATED = "recovery_codes_regenerated"


class MailState(StrEnum):
    # Waiting for its next attempt, or being sent.
    QUEUED = "queued"
    SENT = "sent"
    # The last attempt failed and none follows.
    FAILED = "failed"


class FailureReason(StrEnum):
    """Why an attempt did not send: the kind of SMTP failure, or why no attempt was made."""

    AUTH = "auth"
    CONNECT = "connect"
    TIMEOUT = "timeout"
    TLS = "tls"
    DISCONNECTED = "disconnected"
    RECIPIENT_REFUSED = "recipient_refused"
    SENDER_REFUSED = "sender_refused"
    DATA_REFUSED = "data_refused"
    OTHER = "other"
    # The mailbox was turned off before the mail went.
    MAIL_OFF = "mail_off"
    # Its link stopped working before the mail went.
    EXPIRED = "expired"
    # The mail or the mailbox's password does not open with the install's keys.
    UNREADABLE = "unreadable"


# Without an SMTP code, only these are worth asking again: the connection did not open or broke off.
TEMPORARY_REASONS = frozenset({FailureReason.CONNECT, FailureReason.TIMEOUT, FailureReason.DISCONNECTED})


class MailNotFoundError(NotFoundError):
    code = "mail_not_found"


class MailExpiredError(ConflictError):
    """The mail can no longer be sent: its link stopped working, or it is too old."""

    code = "mail_expired"


class MailQueuedError(ConflictError):
    """The mail is waiting for its next attempt already."""

    code = "mail_queued"


@dataclass(frozen=True, slots=True)
class Failure:
    reason: FailureReason
    # The SMTP server's reply code, when it answered with one.
    smtp_code: int | None = None
    # The server's words, one line, credentials scrubbed.
    text: str | None = None

    @property
    def temporary(self) -> bool:
        """A 4xx reply, or a connection that did not open or broke off: worth trying again later."""
        if self.smtp_code is not None:
            return self.smtp_code in SMTP_TEMPORARY
        return self.reason in TEMPORARY_REASONS

    def describe(self) -> str:
        """What the admin reads: the server's words with their code, or the reason when there are none."""
        if self.text is None:
            return self.reason.value
        return f"{self.smtp_code} {self.text}" if self.smtp_code is not None else self.text


class MailDeliveryError(Exception):
    """Sending failed; the failure is already scrubbed of the mailbox's login and password."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.describe())
        self.failure = failure


@dataclass(frozen=True, slots=True)
class Content:
    subject: str
    text: str
    html: str


@dataclass(frozen=True, slots=True)
class Envelope:
    to: str
    content: Content


class MailTransport(Protocol):
    async def send(self, mailbox: Mailbox, envelope: Envelope) -> str:
        """Send the mail; its ``Message-ID``. ``MailDeliveryError`` when it does not go."""
        ...

    async def probe(self, mailbox: Mailbox) -> None:
        """Connect and sign in without sending; ``MailDeliveryError`` when that fails."""
        ...


@dataclass(slots=True)
class Mail:
    """One email: the queue's row and the log's. Its body is sealed, since links in it open accounts."""

    kind: MailKind
    to_address: str
    locale: str
    subject: str
    created_at: datetime
    # Nothing is sent from then on: its link stops working, or it is too old to matter.
    expires_at: datetime
    # The account it is for, when it is someone's.
    user_id: UUID | None = None
    # Who caused it, when someone signed in did.
    created_by: UUID | None = None
    # Sealed ``Content``; None once it can no longer be sent.
    sealed_content: str | None = None
    state: MailState = MailState.QUEUED
    # Attempts since it was queued or last resent.
    attempts: int = 0
    next_attempt_at: datetime | None = None
    id: UUID = field(default_factory=new_id)

    def sendable(self, now: datetime) -> bool:
        return self.sealed_content is not None and now < self.expires_at


@dataclass(frozen=True, slots=True)
class Attempt:
    mail_id: UUID
    at: datetime
    duration_ms: int
    failure: Failure | None
    message_id: str | None
    # When the next automatic attempt is due, if one is.
    next_attempt_at: datetime | None
    # The admin who sent it by hand: a test, or a resend.
    by: UUID | None = None
    id: UUID = field(default_factory=new_id)

    @property
    def sent(self) -> bool:
        return self.failure is None


@dataclass(frozen=True, slots=True)
class LoggedMail:
    """A mail as the log shows it, with its attempts, the latest first."""

    mail: Mail
    attempts: list[Attempt]


def after_attempt(mail: Mail, failure: Failure | None, now: datetime) -> tuple[MailState, datetime | None]:
    """The mail's state after an attempt that ended with ``failure`` (None: sent), and its next attempt."""
    if failure is None:
        return MailState.SENT, None
    # A test is never retried: the admin waits for its one attempt.
    if mail.kind is not MailKind.TEST and failure.temporary and mail.attempts < MAX_ATTEMPTS:
        return MailState.QUEUED, now + RETRY_DELAYS[mail.attempts - 1]
    return MailState.FAILED, None

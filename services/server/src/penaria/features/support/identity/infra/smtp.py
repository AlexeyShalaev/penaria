"""Sending through the install's SMTP server with aiosmtplib.

Every failure becomes a ``MailDeliveryError`` that says what kind of failure it was, with the
server's reply as the admin should read it: on one line, without the mailbox's login and password,
plain or in the base64 that ``AUTH PLAIN`` and ``AUTH LOGIN`` send them in.
"""

import base64
import contextlib
import re
import ssl
from collections.abc import Iterator
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import aiosmtplib

from penaria.features.support.identity.domain.mail import (
    Envelope,
    Failure,
    FailureReason,
    MailDeliveryError,
)
from penaria.features.support.identity.domain.mailbox import Mailbox, MailSecurity

TIMEOUT_SECONDS = 15
HIDDEN = "[hidden]"
# The log shows one line of the server's words; longer replies are cut.
ERROR_TEXT_MAX_LENGTH = 500
SMTP_CODES = range(100, 1000)

# Order matters: a connect timeout is a connect error too, and a disconnection or timeout is an OSError.
REASONS: tuple[tuple[type[BaseException] | tuple[type[BaseException], ...], FailureReason], ...] = (
    (aiosmtplib.SMTPAuthenticationError, FailureReason.AUTH),
    (aiosmtplib.SMTPRecipientRefused, FailureReason.RECIPIENT_REFUSED),
    (aiosmtplib.SMTPSenderRefused, FailureReason.SENDER_REFUSED),
    (aiosmtplib.SMTPDataError, FailureReason.DATA_REFUSED),
    (aiosmtplib.SMTPConnectResponseError, FailureReason.CONNECT),
    ((aiosmtplib.SMTPTimeoutError, TimeoutError), FailureReason.TIMEOUT),
    (aiosmtplib.SMTPServerDisconnected, FailureReason.DISCONNECTED),
    (aiosmtplib.SMTPResponseException, FailureReason.OTHER),
    # Refused, an unknown host, an unreachable network.
    ((aiosmtplib.SMTPConnectError, OSError), FailureReason.CONNECT),
)


class SmtpTransport:
    async def send(self, mailbox: Mailbox, envelope: Envelope) -> str:
        fields = mailbox.fields
        try:
            message, message_id = _message(mailbox, envelope)
            await aiosmtplib.send(
                message,
                hostname=fields.host,
                port=fields.port,
                use_tls=fields.security is MailSecurity.TLS,
                start_tls=fields.security is MailSecurity.STARTTLS,
                username=fields.username,
                password=mailbox.password if fields.username else None,
                timeout=TIMEOUT_SECONDS,
                # Otherwise aiosmtplib asks the system for its own name, a reverse DNS lookup that may hang.
                local_hostname=_domain(fields.from_address),
            )
        except Exception as exc:
            raise MailDeliveryError(classify(exc, login=fields.username, password=mailbox.password)) from exc
        return message_id

    async def probe(self, mailbox: Mailbox) -> None:
        fields = mailbox.fields
        client: aiosmtplib.SMTP | None = None
        try:
            client = aiosmtplib.SMTP(
                hostname=fields.host,
                port=fields.port,
                use_tls=fields.security is MailSecurity.TLS,
                start_tls=False,
                timeout=TIMEOUT_SECONDS,
                local_hostname=_domain(fields.from_address),
            )
            await client.connect()
            if fields.security is MailSecurity.STARTTLS:
                await client.starttls()
            if fields.username:
                await client.login(fields.username, mailbox.password or "")
            await client.noop()
        except Exception as exc:
            raise MailDeliveryError(classify(exc, login=fields.username, password=mailbox.password)) from exc
        finally:
            # The connection may not have opened, or the server may have dropped it already.
            if client is not None:
                with contextlib.suppress(aiosmtplib.SMTPException, OSError):
                    await client.quit()


def classify(exc: BaseException, *, login: str | None, password: str | None) -> Failure:
    """The failure an exception of aiosmtplib, ``ssl`` or the network stands for, its text scrubbed of the
    mailbox's login and password."""
    source = exc
    code: int | None = None
    if isinstance(exc, aiosmtplib.SMTPRecipientsRefused) and exc.recipients:
        source = exc.recipients[0]
        reason = FailureReason.RECIPIENT_REFUSED
    elif isinstance(exc, aiosmtplib.SMTPNotSupported):
        lowered = str(exc).lower()
        reason = (
            FailureReason.TLS if "tls" in lowered else FailureReason.AUTH if "auth" in lowered else FailureReason.OTHER
        )
    elif not isinstance(exc, aiosmtplib.SMTPResponseException) and any(
        isinstance(e, ssl.SSLError) for e in _chain(exc)
    ):
        reason = FailureReason.TLS
    else:
        reason = next((r for kind, r in REASONS if isinstance(exc, kind)), FailureReason.OTHER)
    if isinstance(source, aiosmtplib.SMTPResponseException) and source.code in SMTP_CODES:
        code = source.code
    text = _words(source)
    if not isinstance(source, aiosmtplib.SMTPException):
        text = f"{type(source).__name__}: {text}" if text else type(source).__name__
    return Failure(reason=reason, smtp_code=code, text=scrub(text, login=login, password=password))


def scrub(text: str, *, login: str | None, password: str | None) -> str | None:
    """``text`` on one line, at most 500 characters, with the login and the password hidden, plain or in the
    base64 that ``AUTH LOGIN`` and ``AUTH PLAIN`` send them in."""
    plain = [secret for secret in (login, password) if secret]
    variants = plain + [base64.b64encode(secret.encode()).decode() for secret in plain]
    if login and password:
        variants.append(base64.b64encode(f"\0{login}\0{password}".encode()).decode())
    hidden = sorted(set(variants), key=len, reverse=True)
    if hidden:
        text = re.compile("|".join(re.escape(secret) for secret in hidden), re.IGNORECASE).sub(HIDDEN, text)
    one_line = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return one_line[:ERROR_TEXT_MAX_LENGTH] or None


def _message(mailbox: Mailbox, envelope: Envelope) -> tuple[EmailMessage, str]:
    """The email as text and HTML, and its ``Message-ID``."""
    fields = mailbox.fields
    message = EmailMessage()
    local = fields.from_address.rpartition("@")[0]
    message["From"] = formataddr((fields.from_name, f"{local}@{_domain(fields.from_address)}"))
    message["To"] = envelope.to
    message["Subject"] = envelope.content.subject
    message_id = make_msgid(domain=_domain(fields.from_address))
    message["Message-ID"] = message_id
    # RFC 3834: out-of-office replies and other robots should not answer.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(envelope.content.text)
    message.add_alternative(envelope.content.html, subtype="html")
    return message, message_id


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """The exception and its causes: aiosmtplib wraps a TLS failure into a connection error."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _words(exc: BaseException) -> str:
    if isinstance(exc, aiosmtplib.SMTPResponseException):
        return exc.message
    return str(exc)


def _domain(address: str) -> str:
    """The domain of an address as SMTP sends it, in ASCII: ``почта.рф`` as ``xn--80a1acny.xn--p1ai``."""
    domain = address.rpartition("@")[2]
    return domain.encode("idna").decode("ascii") if domain else "localhost"

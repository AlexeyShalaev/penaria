"""The install's one mailbox: the SMTP server it sends every email through (sign-in.md, 9.1)."""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from penaria.features.shared.errors import ConflictError, ForbiddenError, InvalidError

HOST_MAX_LENGTH = 253
LOGIN_MAX_LENGTH = 320
SENDER_NAME_MAX_LENGTH = 100
EMAIL_MAX_LENGTH = 254
PORT_MAX = 65535
DEFAULT_SENDER_NAME = "Penaria"
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# The record the saved password is sealed for (domain/secrets.py).
MAILBOX_SEAL = "mailbox/password"
# A host name, an IPv4 address or a bracketless IPv6 one: no spaces, slashes or credentials.
HOST_PATTERN = re.compile(r"[A-Za-z0-9.:_-]+")


class MailSecurity(StrEnum):
    STARTTLS = "starttls"
    TLS = "tls"
    NONE = "none"


# The port each kind of security usually listens on; the form moves to it when the security changes.
DEFAULT_PORTS = {MailSecurity.STARTTLS: 587, MailSecurity.TLS: 465, MailSecurity.NONE: 25}


class MailboxSource(StrEnum):
    # PENARIA_MAIL__*: the operator's, locked in the interface.
    ENVIRONMENT = "environment"
    # Saved by an install admin in the interface.
    INTERFACE = "interface"


class InvalidMailboxError(InvalidError):
    code = "invalid_mailbox"


class InvalidEmailError(InvalidError):
    code = "invalid_email"


class MailboxLockedError(ConflictError):
    """The mailbox comes from PENARIA_MAIL__*, so the interface cannot change it."""

    code = "mailbox_locked"


class MailOffError(ConflictError):
    """The install has no mailbox: links are passed on by hand instead."""

    code = "mail_off"


class InstallAdminRequiredError(ForbiddenError):
    code = "install_admin_required"


@dataclass(frozen=True, slots=True)
class MailboxFields:
    """The mailbox as an admin sees and edits it; the password is write-only, so only whether one is set."""

    host: str
    port: int
    security: MailSecurity
    username: str | None
    from_address: str
    from_name: str

    @classmethod
    def check(
        cls,
        *,
        host: str,
        port: int,
        security: MailSecurity,
        username: str | None,
        from_address: str,
        from_name: str | None,
    ) -> MailboxFields:
        """The fields, trimmed and checked; an error names the field that is wrong."""
        host = host.strip()
        if not host or len(host) > HOST_MAX_LENGTH or not HOST_PATTERN.fullmatch(host):
            raise InvalidMailboxError("the server is a host name or an address", params={"field": "host"})
        if not 1 <= port <= PORT_MAX:
            raise InvalidMailboxError("the port is from 1 to 65535", params={"field": "port"})
        login = (username or "").strip()
        if len(login) > LOGIN_MAX_LENGTH or any(c.isspace() for c in login):
            raise InvalidMailboxError("the login has no spaces", params={"field": "username"})
        name = " ".join((from_name or "").split()) or DEFAULT_SENDER_NAME
        if len(name) > SENDER_NAME_MAX_LENGTH:
            raise InvalidMailboxError(
                "the sender's name is at most 100 characters", params={"field": "from_name", "max_length": 100}
            )
        return cls(
            host=host,
            port=port,
            security=security,
            username=login or None,
            from_address=check_email(from_address, field="from_address"),
            from_name=name,
        )


@dataclass(frozen=True, slots=True)
class Mailbox:
    """What sending needs: the fields and the password, which lives in plain text only in memory."""

    fields: MailboxFields
    password: str | None
    source: MailboxSource

    def __repr__(self) -> str:
        return f"Mailbox(host={self.fields.host!r}, port={self.fields.port}, source={self.source.value})"


@dataclass(frozen=True, slots=True)
class OperatorMailbox:
    """The mailbox of ``PENARIA_MAIL__*``, when the operator set one: it wins over the interface's as a whole."""

    mailbox: Mailbox | None


@dataclass(frozen=True, slots=True)
class StoredMailbox:
    """The mailbox an admin saved: the fields, and the password sealed with the install's key."""

    fields: MailboxFields
    sealed_password: str | None


def check_email(email: str, *, field: str = "email") -> str:
    """The address as stored and compared, in lower case; an error names ``field`` when it is not one."""
    normalized = unicodedata.normalize("NFKC", email).strip().lower()
    if len(normalized) > EMAIL_MAX_LENGTH or not EMAIL_PATTERN.fullmatch(normalized):
        raise InvalidEmailError("this is not an email address", params={"field": field})
    return normalized

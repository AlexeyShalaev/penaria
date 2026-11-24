"""Passkeys: WebAuthn credentials that sign people in without a password (sign-in.md, 4.1)."""

import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from penaria.features.shared.errors import ConflictError, InvalidError, NotFoundError, UnauthenticatedError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.throttle import TooManyAttemptsError

# How long a ceremony may take, from the options to the answer: enough to pick a phone through a QR code.
CEREMONY_TIMEOUT = timedelta(minutes=5)
# WebAuthn asks for at least 16 random bytes.
CHALLENGE_BYTES = 32
# Sign-in challenges need no account, so each address may hold only so many open ones: plenty for a
# household behind one address, while a script cannot fill the table.
OPEN_SIGN_INS_PER_ADDRESS = 10
NAME_MAX_LENGTH = 100

# A credential as the browser serializes it (PublicKeyCredential.toJSON()), checked by the relying party.
CredentialJson = Mapping[str, Any]


class InvalidPasskeyError(UnauthenticatedError):
    """The same answer for an unknown passkey, a wrong signature, an expired ceremony and a disabled account."""

    code = "invalid_passkey"


class PasskeyRejectedError(InvalidError):
    """A passkey made or used for the signed-in account did not check out, or its ceremony expired."""

    code = "passkey_rejected"


class PasskeyAlreadyRegisteredError(ConflictError):
    code = "passkey_already_registered"


class PasskeyNotFoundError(NotFoundError):
    code = "passkey_not_found"


class InvalidPasskeyNameError(InvalidError):
    code = "invalid_passkey_name"


class LastSignInMethodError(ConflictError):
    code = "last_sign_in_method"


class CredentialRejected(Exception):  # noqa: N818 - a verdict of the relying party, turned into the errors above
    """What the browser sent is not a valid answer to the ceremony; the message says why, for the log."""


class Ceremony(StrEnum):
    REGISTRATION = "registration"
    SIGN_IN = "sign_in"
    REAUTHENTICATION = "reauthentication"


@dataclass(frozen=True, slots=True)
class Challenge:
    """A challenge the server gave out, used at most once before it expires.

    A registration or a confirmation belongs to the session that asked for it. A sign-in belongs to
    none; it keeps the address it was asked from (its counter key), so one address cannot hold many.
    """

    ceremony: Ceremony
    value: bytes
    session_id: UUID | None
    expires_at: datetime
    address: str | None = None
    id: UUID = field(default_factory=new_id)

    @classmethod
    def for_session(
        cls, ceremony: Literal[Ceremony.REGISTRATION, Ceremony.REAUTHENTICATION], session_id: UUID, now: datetime
    ) -> Challenge:
        return cls(ceremony, secrets.token_bytes(CHALLENGE_BYTES), session_id, now + CEREMONY_TIMEOUT)

    @classmethod
    def for_sign_in(cls, address: str | None, now: datetime) -> Challenge:
        return cls(Ceremony.SIGN_IN, secrets.token_bytes(CHALLENGE_BYTES), None, now + CEREMONY_TIMEOUT, address)


@dataclass(frozen=True, slots=True)
class PasskeyOptions:
    """What the browser needs for a ceremony: the options for ``navigator.credentials`` and the id of
    their challenge, which comes back with the answer."""

    challenge_id: UUID
    options: dict[str, Any]


def check_open_sign_ins(expiries: Sequence[datetime], now: datetime) -> None:
    """Refuse another sign-in challenge to an address that holds too many open ones (their expiries)."""
    if len(expiries) >= OPEN_SIGN_INS_PER_ADDRESS:
        wait = min(expiries) - now
        raise TooManyAttemptsError(
            "too many sign-ins started; wait and try again",
            params={"retry_after_seconds": int(wait.total_seconds()) + 1},
        )


@dataclass(slots=True)
class Passkey:
    user_id: UUID
    credential_id: bytes
    public_key: bytes
    sign_count: int
    name: str
    created_at: datetime
    # How the browser may reach the authenticator again (usb, nfc, ble, hybrid, internal); a hint only.
    transports: list[str] = field(default_factory=list)
    last_used_at: datetime | None = None
    id: UUID = field(default_factory=new_id)


@dataclass(frozen=True, slots=True)
class NewCredential:
    """A credential the relying party checked when it was made."""

    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: list[str]


@dataclass(frozen=True, slots=True)
class Assertion:
    """Which credential an answer to a sign-in names, read before it is checked."""

    credential_id: bytes
    # The account the authenticator keeps the credential for; discoverable credentials always say.
    user_handle: bytes | None


class RelyingParty(Protocol):
    """The WebAuthn relying party of the install: its options, and the checks of what browsers answer."""

    def registration_options(self, user: User, challenge: Challenge, existing: Sequence[Passkey]) -> dict[str, Any]: ...

    def verify_registration(self, credential: CredentialJson, challenge: Challenge) -> NewCredential:
        """The checked credential; ``CredentialRejected`` when it is not a valid answer."""
        ...

    def authentication_options(self, challenge: Challenge, allowed: Sequence[Passkey]) -> dict[str, Any]:
        """Options for ``navigator.credentials.get``; no ``allowed`` passkeys lets the person pick any."""
        ...

    def read_assertion(self, credential: CredentialJson) -> Assertion:
        """The credential an answer names; ``CredentialRejected`` when it cannot be read."""
        ...

    def verify_authentication(self, credential: CredentialJson, challenge: Challenge, passkey: Passkey) -> int:
        """The passkey's new signature count; ``CredentialRejected`` when the answer does not check out."""
        ...


def user_handle(user: User) -> bytes:
    """The id the authenticator keeps a credential under: the account's id, which says nothing about the person."""
    return user.id.bytes


def check_passkey_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > NAME_MAX_LENGTH:
        raise InvalidPasskeyNameError(
            f"a passkey's name has 1 to {NAME_MAX_LENGTH} characters", params={"max_length": NAME_MAX_LENGTH}
        )
    return cleaned

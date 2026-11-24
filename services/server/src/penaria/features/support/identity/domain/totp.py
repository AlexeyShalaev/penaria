"""The second factor: one-time codes from an authenticator app (TOTP, RFC 6238) and single-use recovery codes
(sign-in.md, 4.3).

The codes are computed here with the standard library: RFC 6238 over RFC 4226 is an HMAC and a few
lines of arithmetic, checked against the RFC's own test vectors, which is less than a dependency.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode
from uuid import UUID

from penaria.features.shared.errors import ConflictError, ForbiddenError, InvalidError, UnauthenticatedError
from penaria.features.shared.ids import new_id
from penaria.features.support.identity.domain.sessions import new_secret

ISSUER = "Penaria"
# What every authenticator app understands: SHA-1, six digits, a new code every 30 seconds.
STEP_SECONDS = 30
DIGITS = 6
# RFC 4226 asks for at least 128 bits and recommends 160.
SECRET_BYTES = 20
# A code of the step before or after the current one is accepted too: the phone's clock may be off,
# and a person needs a few seconds to type a code.
WINDOW_STEPS = 1
# Starting the set-up shows the secret; it must be confirmed with a code within this time.
ENROLMENT_TIMEOUT = timedelta(minutes=10)
RECOVERY_CODE_COUNT = 10
# Crockford's base32: no i, l, o or u, so a code read off paper is not mistyped; 16 of them are 80 bits,
# enough that a stolen hash cannot be reversed by trying every code.
RECOVERY_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
RECOVERY_CODE_LENGTH = 16
RECOVERY_GROUP = 4
# Letters people type for the digits they look like (Crockford's base32).
RECOVERY_LOOKALIKES = str.maketrans({"o": "0", "i": "1", "l": "1"})
# The second step of signing in with a password must follow within this time.
PENDING_SIGN_IN_LIFETIME = timedelta(minutes=5)


class WrongCodeError(InvalidError):
    """A code from the authenticator app, or a recovery code, that does not check out."""

    code = "wrong_code"


class SecondFactorExpiredError(UnauthenticatedError):
    """The second step of a sign-in came too late, from elsewhere, or was already done: sign in again."""

    code = "second_factor_expired"


class SecondFactorCodeRequiredError(InvalidError):
    code = "second_factor_code_required"


class TotpAlreadyEnabledError(ConflictError):
    code = "totp_already_enabled"


class TotpNotEnabledError(ConflictError):
    code = "totp_not_enabled"


class TotpEnrolmentNotFoundError(ConflictError):
    """No set-up of the authenticator app is waiting for its code: it was never started, or took too long."""

    code = "totp_enrolment_not_found"


class TotpUnreadableError(ConflictError):
    """The authenticator app's secret does not open with the install's keys: a recovery code still works."""

    code = "totp_unreadable"


class LastSecondFactorError(ConflictError):
    """Turning the authenticator app off would leave an owner or an install admin with a password alone."""

    code = "last_second_factor"


class SecondFactorRequiredError(ForbiddenError):
    """An owner or an install admin who signs in with a password must add a second factor before this."""

    code = "second_factor_required"


@dataclass(slots=True)
class Totp:
    """An account's authenticator app: waiting for its first code, or turned on (``confirmed_at``)."""

    user_id: UUID
    # The base32 secret, sealed with PENARIA_SECRET_KEY (domain/secrets.py) and bound to ``bound_to``.
    sealed_secret: str
    created_at: datetime
    confirmed_at: datetime | None = None
    # The step of the last code accepted: that code and every earlier one are refused from then on.
    last_used_step: int | None = None
    # Hashes of the recovery codes not used yet (``hash_recovery_code``).
    recovery_codes: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.confirmed_at is not None

    def enrolment_open(self, now: datetime) -> bool:
        return not self.enabled and now < self.created_at + ENROLMENT_TIMEOUT

    def use_code(self, secret: str, code: str, now: datetime) -> None:
        """Accept a code of the app, once: ``WrongCodeError`` for a wrong one or one already used."""
        step = matching_step(secret, code, now, after=self.last_used_step)
        if step is None:
            raise WrongCodeError("the code is wrong or was already used: wait for the next one")
        self.last_used_step = step

    def use_recovery_code(self, code: str) -> None:
        """Accept a recovery code, once: it is crossed off."""
        hashed = hash_recovery_code(code)
        matches = [kept for kept in self.recovery_codes if hmac.compare_digest(kept, hashed)]
        if not matches:
            raise WrongCodeError("the recovery code is wrong or was already used")
        self.recovery_codes = [kept for kept in self.recovery_codes if kept != hashed]


def must_keep_second_factor(*, has_password: bool, install_admin: bool, owns_a_home: bool) -> bool:
    """Whether an account must have a second factor (sign-in.md, 4.3): an install admin or an owner of any home
    who can sign in with a password. A passkey is one by itself, so an account without a password needs none."""
    return has_password and (install_admin or owns_a_home)


def bound_to(user_id: UUID) -> str:
    """The record a TOTP secret is sealed for, so it opens only as this account's."""
    return f"totp/{user_id}"


@dataclass(frozen=True, slots=True)
class PendingSignIn:
    """A sign-in whose password was right and whose second factor is still to come.

    Only a hash of its token is kept; it works from the address the password came from, for a few
    minutes, and opens one session at most.
    """

    user_id: UUID
    token_hash: bytes
    # The counter key of the address (domain/throttle.py); None for a request without one.
    address: str | None
    created_at: datetime
    expires_at: datetime
    id: UUID = field(default_factory=new_id)

    @classmethod
    def start(cls, user_id: UUID, address: str | None, now: datetime) -> tuple[PendingSignIn, str]:
        token, token_hash = new_secret()
        pending = cls(
            user_id=user_id,
            token_hash=token_hash,
            address=address,
            created_at=now,
            expires_at=now + PENDING_SIGN_IN_LIFETIME,
        )
        return pending, token


def new_secret_key() -> str:
    """A new TOTP secret, in the base32 people type into an authenticator app by hand (no padding)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def provisioning_uri(secret: str, username: str, host: str) -> str:
    """The ``otpauth://`` address a QR code carries to the app: "Penaria", and the account as username@host."""
    label = quote(f"{ISSUER}:{username}@{host}", safe=":@")
    query = urlencode(
        {"secret": secret, "issuer": ISSUER, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS}
    )
    return f"otpauth://totp/{label}?{query}"


def step_at(now: datetime) -> int:
    return int(now.timestamp()) // STEP_SECONDS


def code_at(secret: str, step: int) -> str:
    """The code of ``step`` (RFC 4226's HOTP of the step counter)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def matching_step(secret: str, code: str, now: datetime, *, after: int | None) -> int | None:
    """The step whose code ``code`` is, within the window around ``now`` and later than ``after``; else None."""
    typed = "".join(code.split())
    if len(typed) != DIGITS or not typed.isascii() or not typed.isdigit():
        return None
    current = step_at(now)
    for step in range(current - WINDOW_STEPS, current + WINDOW_STEPS + 1):
        if (after is None or step > after) and hmac.compare_digest(code_at(secret, step), typed):
            return step
    return None


def new_recovery_codes() -> list[str]:
    """Ten new recovery codes, as people see them: four groups of four, such as ``7kq2-m9xd-3hfa-wp0e``."""
    return [_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]


def hash_recovery_code(code: str) -> str:
    """What is kept of a recovery code; the same for the code however it is typed (case, dashes, spaces)."""
    normalized = "".join(char for char in code.lower() if char.isalnum()).translate(RECOVERY_LOOKALIKES)
    return hashlib.sha256(normalized.encode()).hexdigest()


def _recovery_code() -> str:
    chars = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
    return "-".join(chars[i : i + RECOVERY_GROUP] for i in range(0, RECOVERY_CODE_LENGTH, RECOVERY_GROUP))

"""The signed-in person's authenticator app and recovery codes (sign-in.md, 4.3).

Setting the app up shows a secret once and keeps it sealed; the app is on only after its first
code, so a secret that never reached the app locks nobody out. Recovery codes are shown once, when
the app is turned on or the codes are renewed; only their hashes are kept.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.accounts import normalize_username
from penaria.features.support.identity.domain.links import PublicLinks
from penaria.features.support.identity.domain.mail import MailKind
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.secrets import SecretBox
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.domain.throttle import second_factor_key
from penaria.features.support.identity.domain.totp import (
    ENROLMENT_TIMEOUT,
    LastSecondFactorError,
    Totp,
    TotpAlreadyEnabledError,
    TotpEnrolmentNotFoundError,
    TotpNotEnabledError,
    bound_to,
    hash_recovery_code,
    new_recovery_codes,
    new_secret_key,
    provisioning_uri,
)
from penaria.features.support.identity.use_cases.account import load_user
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.recovery import AccountNotFoundError
from penaria.features.support.identity.use_cases.second_factor import (
    must_have_second_factor,
    open_secret,
    totp_enabled,
)


@dataclass(frozen=True, slots=True)
class SecondFactorStatus:
    totp_enabled_at: datetime | None
    # None while the app is off.
    recovery_codes_left: int | None
    # The account is an owner or an install admin with a password: it must keep a second factor.
    required: bool
    # Required, and it has neither an app nor a passkey: owner-level commands refuse it until it adds one.
    missing: bool


@dataclass(frozen=True, slots=True)
class TotpEnrolment:
    """What the person puts into the authenticator app: the secret typed by hand, or the address a QR code carries."""

    secret: str
    uri: str
    expires_at: datetime


class GetSecondFactor:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> SecondFactorStatus:
        async with self._uow.query() as tx:
            user = await load_user(tx, current)
            totp = await totp_enabled(tx, user.id)
            required = await must_have_second_factor(tx, user)
            missing = required and totp is None and not await tx.passkeys.for_user(user.id)
            return SecondFactorStatus(
                totp_enabled_at=None if totp is None else totp.confirmed_at,
                recovery_codes_left=None if totp is None else len(totp.recovery_codes),
                required=required,
                missing=missing,
            )


class StartTotpEnrolment:
    """A new secret for the authenticator app; the app is on once ``ConfirmTotp`` takes its first code.

    Starting again replaces a set-up that was not finished. Like adding a passkey, it needs a recent sign-in.
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], box: SecretBox, links: PublicLinks) -> None:
        self._uow = uow
        self._box = box
        self._links = links

    async def execute(self, current: CurrentSession) -> TotpEnrolment:
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        secret = new_secret_key()
        sealed = self._box.seal(secret, bound_to=bound_to(current.user_id))
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None or user.username is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session has no account")
            if await totp_enabled(tx, user.id) is not None:
                raise TotpAlreadyEnabledError("the authenticator app is on already: turn it off first to replace it")
            await tx.totp.save(Totp(user_id=user.id, sealed_secret=sealed, created_at=now))
        return TotpEnrolment(
            secret=secret,
            uri=provisioning_uri(secret, user.username, self._links.host),
            expires_at=now + ENROLMENT_TIMEOUT,
        )


class ConfirmTotp:
    """Turn the authenticator app on with its first code; the recovery codes, shown only now."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], box: SecretBox, postman: Postman) -> None:
        self._uow = uow
        self._box = box
        self._postman = postman

    async def execute(self, current: CurrentSession, code: str) -> list[str]:
        # Guessing the first code from a stolen session would hand over the recovery codes: limited as signing in.
        attempts = second_factor_key(current.user_id)
        async with self._uow.transaction() as tx:
            await count_attempt(tx, [attempts], datetime.now(UTC))
        now = datetime.now(UTC)
        codes = new_recovery_codes()
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            totp = await tx.totp.get(user.id)
            if totp is not None and totp.enabled:
                raise TotpAlreadyEnabledError("the authenticator app is on already")
            if totp is None or not totp.enrolment_open(now):
                raise TotpEnrolmentNotFoundError("setting up the authenticator app took too long: start again")
            totp.use_code(open_secret(self._box, totp), code, now)
            await attempt_succeeded(tx, attempts)
            totp.confirmed_at = now
            totp.recovery_codes = [hash_recovery_code(c) for c in codes]
            await tx.totp.save(totp)
            await tx.journal.append([_event("account.totp_enabled", user.id)])
            await self._postman.notify(tx, user, MailKind.TOTP_ENABLED)
        return codes


class RegenerateRecoveryCodes:
    """Ten new recovery codes, shown only now; the earlier ones stop working."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], postman: Postman) -> None:
        self._uow = uow
        self._postman = postman

    async def execute(self, current: CurrentSession) -> list[str]:
        now = datetime.now(UTC)
        current.require_recent_sign_in(now)
        codes = new_recovery_codes()
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            totp = await totp_enabled(tx, user.id)
            if totp is None:
                raise TotpNotEnabledError("the authenticator app is off: recovery codes come with it")
            totp.recovery_codes = [hash_recovery_code(c) for c in codes]
            await tx.totp.save(totp)
            await tx.journal.append([_event("account.recovery_codes_regenerated", user.id)])
            await self._postman.notify(tx, user, MailKind.RECOVERY_CODES_REGENERATED)
        return codes


class TurnOffTotp:
    """Turn the authenticator app off, with its recovery codes. An owner or an install admin keeps it
    unless they have a passkey: they must not be left with a password alone."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], postman: Postman) -> None:
        self._uow = uow
        self._postman = postman

    async def execute(self, current: CurrentSession) -> None:
        current.require_recent_sign_in(datetime.now(UTC))
        async with self._uow.transaction() as tx:
            # Taken as removing a passkey takes it, so the two never leave the account without both at once.
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            if await totp_enabled(tx, user.id) is None:
                raise TotpNotEnabledError("the authenticator app is off already")
            if not await tx.passkeys.for_user(user.id) and await must_have_second_factor(tx, user):
                raise LastSecondFactorError(
                    "owners and install admins keep a second factor: add a passkey before turning the app off"
                )
            await tx.totp.remove(user.id)
            await tx.journal.append([_event("account.totp_disabled", user.id)])
            await self._postman.notify(tx, user, MailKind.TOTP_DISABLED)


class TurnOffTotpByOperator:
    """The operator turns an account's authenticator app off from the command line, for a person who lost
    both the app and the recovery codes (sign-in.md, 8). Access to the server is access to the house."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, username: str) -> bool:
        """Whether the account had an authenticator app to turn off."""
        async with self._uow.transaction() as tx:
            user = await tx.users.by_username(normalize_username(username))
            if user is None:
                raise AccountNotFoundError(f"no account has the username {username!r}")
            await tx.users.get_for_update(user.id)
            enabled = await totp_enabled(tx, user.id) is not None
            # A set-up never confirmed goes too, but there was no app to turn off.
            await tx.totp.remove(user.id)
            if not enabled:
                return False
            await tx.journal.append([_event("account.totp_disabled", user.id, actor=Actor.system(), by="operator")])
        return True


def _event(event_type: str, user_id: UUID, *, actor: Actor | None = None, **payload: str) -> Event:
    return Event(event_type, None, actor or Actor.user(user_id), {"user_id": str(user_id), **payload})

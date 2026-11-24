"""Signing in and out, and finding the account behind a request's session."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import UnauthenticatedError
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.accounts import normalize_username
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passkeys import (
    Assertion,
    Ceremony,
    Challenge,
    CredentialJson,
    CredentialRejected,
    InvalidPasskeyError,
    Passkey,
    PasskeyOptions,
    RelyingParty,
    user_handle,
)
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, Session, hash_token
from penaria.features.support.identity.domain.throttle import account_key, address_key
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt
from penaria.features.support.identity.use_cases.challenges import issue_challenge

logger = logging.getLogger(__name__)


class InvalidCredentialsError(UnauthenticatedError):
    """The same answer for an unknown username, a wrong password and a disabled account."""

    code = "invalid_credentials"


class Authenticate:
    """The session behind a request's cookie, if it is still open."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, token: str | None) -> CurrentSession:
        if not token:
            raise UnauthenticatedError("sign in first")
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            found = await tx.sessions.by_token_hash(hash_token(token))
            if found is None:
                raise UnauthenticatedError("sign in first")
            session, user = found
            if not session.is_active(now) or user.disabled_at is not None:
                raise UnauthenticatedError("the session has ended; sign in again")
            if session.needs_touch(now):
                await tx.sessions.touch(session.id, now)
        return CurrentSession(id=session.id, user_id=user.id, authenticated_at=session.authenticated_at)


class SignIn:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(self, *, username: str, password: str, client: Client) -> tuple[User, str]:
        """The account and a new session's token; every kind of failure answers the same."""
        username = normalize_username(username)
        account = account_key(username)
        address = address_key(client.ip)
        others = [] if address is None else [address]
        async with self._uow.transaction() as tx:
            await count_attempt(tx, [account, *others], datetime.now(UTC))
            user = await tx.users.by_username(username)
            password_hash = None if user is None else await tx.passwords.get(user.id)
        matches = await self._hasher.verify(password_hash, password)
        if user is None or password_hash is None or not matches or user.disabled_at is not None:
            if user is not None:
                await self._journal_failure(user, client)
            raise InvalidCredentialsError("wrong username or password")
        new_hash = await self._hasher.hash(password) if self._hasher.needs_rehash(password_hash) else None
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await attempt_succeeded(tx, account, others)
            # The password may have changed while it was checked: the old one opens no session.
            if await tx.passwords.get(user.id) != password_hash:
                raise InvalidCredentialsError("wrong username or password")
            if new_hash is not None:
                await tx.passwords.set(user.id, new_hash, now)
            token = await start_session(tx, user, client, now)
        return user, token

    async def _journal_failure(self, user: User, client: Client) -> None:
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [Event("account.sign_in_failed", None, Actor.system(), {"user_id": str(user.id), "ip": client.ip})]
            )


class StartPasskeySignIn:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(self, client: Client) -> PasskeyOptions:
        """The options for ``navigator.credentials.get`` that let the person pick any passkey."""
        now = datetime.now(UTC)
        challenge = Challenge.for_sign_in(address_key(client.ip), now)
        async with self._uow.transaction() as tx:
            await issue_challenge(tx, challenge, now)
        return PasskeyOptions(challenge.id, self._relying_party.authentication_options(challenge, []))


class SignInWithPasskey:
    """A session for whoever answers a sign-in challenge with one of an account's passkeys.

    Failures are limited per address only: a passkey cannot be guessed, and the owner's passkey keeps
    working while someone tries their password (sign-in.md, 12).
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(self, *, challenge_id: UUID, credential: CredentialJson, client: Client) -> tuple[User, str]:
        """The account and a new session's token; every kind of failure answers the same."""
        address = address_key(client.ip)
        attempts = [] if address is None else [address]
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await count_attempt(tx, attempts, now)
            challenge = await tx.challenges.take(challenge_id, Ceremony.SIGN_IN, None, now)
        # Committed before anything is checked, so a failure stays counted.
        if challenge is None:
            raise InvalidPasskeyError("signing in took too long or was already done; start again")
        try:
            assertion = self._relying_party.read_assertion(credential)
        except CredentialRejected as exc:
            raise InvalidPasskeyError("this passkey does not work here") from exc
        passkey, user = await self._passkey_of(assertion)
        try:
            sign_count = self._verify(credential, assertion, challenge, passkey, user)
        except CredentialRejected as exc:
            logger.info("A passkey of an account was refused at sign-in: %s", exc)
            await self._journal_failure(user, passkey, client)
            raise InvalidPasskeyError("this passkey does not work here") from exc
        if user.disabled_at is not None:
            raise InvalidPasskeyError("this passkey does not work here")
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await tx.failures.uncount(attempts)
            # Removed meanwhile, or used by another sign-in since it was read: that one counts.
            if not await tx.passkeys.record_use(passkey.id, passkey.sign_count, sign_count, now):
                raise InvalidPasskeyError("this passkey does not work here")
            token = await start_session(tx, user, client, now, passkey_id=passkey.id)
        return user, token

    def _verify(
        self, credential: CredentialJson, assertion: Assertion, challenge: Challenge, passkey: Passkey, user: User
    ) -> int:
        # Nobody named the account beforehand, so the authenticator must say whose credential it is.
        if assertion.user_handle != user_handle(user):
            raise CredentialRejected("the authenticator keeps the credential for another account, or names none")
        return self._relying_party.verify_authentication(credential, challenge, passkey)

    async def _passkey_of(self, assertion: Assertion) -> tuple[Passkey, User]:
        async with self._uow.query() as tx:
            found = await tx.passkeys.by_credential_id(assertion.credential_id)
        if found is None:
            raise InvalidPasskeyError("this passkey does not work here")
        return found

    async def _journal_failure(self, user: User, passkey: Passkey, client: Client) -> None:
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [
                    Event(
                        "account.sign_in_failed",
                        None,
                        Actor.system(),
                        {"user_id": str(user.id), "ip": client.ip, "passkey_id": str(passkey.id)},
                    )
                ]
            )


class SignOut:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> None:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await tx.sessions.revoke(current.user_id, current.id, now)
            await tx.journal.append(
                [
                    Event(
                        "account.signed_out",
                        None,
                        Actor.user(current.user_id),
                        {"user_id": str(current.user_id), "session_id": str(current.id)},
                    )
                ]
            )


async def start_session(
    tx: IdentityTransaction, user: User, client: Client, now: datetime, *, passkey_id: UUID | None = None
) -> str:
    """Open a session for the user in the transaction and journal the sign-in; the token for the cookie.

    ``passkey_id`` names the passkey the person signed in with; without it, they used their password.
    """
    session, token = Session.start(user.id, client, now)
    await tx.sessions.add(session)
    payload = {"user_id": str(user.id), "session_id": str(session.id), "ip": client.ip}
    if passkey_id is not None:
        payload["passkey_id"] = str(passkey_id)
    await tx.journal.append([Event("account.signed_in", None, Actor.user(user.id), payload)])
    return token

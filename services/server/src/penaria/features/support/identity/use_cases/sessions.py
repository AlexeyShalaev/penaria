"""Signing in and out, and finding the account behind a request's session."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import UnauthenticatedError
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.accounts import normalize_username
from penaria.features.support.identity.domain.models import Grant, User
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
    check_open_sign_ins,
    user_handle,
)
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.secrets import SecretBox
from penaria.features.support.identity.domain.sessions import (
    Client,
    CurrentSession,
    GuestSession,
    RequestSession,
    Session,
    hash_token,
)
from penaria.features.support.identity.domain.throttle import account_key, address_key, second_factor_key
from penaria.features.support.identity.domain.totp import PendingSignIn, SecondFactorExpiredError, WrongCodeError
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt
from penaria.features.support.identity.use_cases.challenges import issue_challenge
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.second_factor import (
    SecondFactorMethod,
    SecondFactorProof,
    method_of,
    prove_second_factor,
    totp_enabled,
)

logger = logging.getLogger(__name__)


class InvalidCredentialsError(UnauthenticatedError):
    """The same answer for an unknown username, a wrong password and a disabled account."""

    code = "invalid_credentials"


@dataclass(frozen=True, slots=True)
class SignedIn:
    user: User
    # The new session's token, for the cookie.
    token: str


@dataclass(frozen=True, slots=True)
class SecondFactorAsked:
    """The password was right, and the account's authenticator app must confirm it before a session opens."""

    # The pending sign-in's token, which the second step brings back.
    token: str
    expires_at: datetime


class Authenticate:
    """The session behind a request's cookie, if it is still open: an account's, or a guest's."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, token: str | None) -> RequestSession:
        if not token:
            raise UnauthenticatedError("sign in first")
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            found = await tx.sessions.by_token_hash(hash_token(token))
            if found is None:
                raise UnauthenticatedError("sign in first")
            session, user, grant = found
            current = _open(session, user, grant, now)
            if session.needs_touch(now):
                await tx.sessions.touch(session.id, now)
        return RequestSession(current)


class SignIn:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(self, *, username: str, password: str, client: Client) -> SignedIn | SecondFactorAsked:
        """A new session; or, for an account with an authenticator app, the second step it needs first.
        Every kind of failure answers the same."""
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
            if await totp_enabled(tx, user.id) is not None:
                await tx.pending_sign_ins.forget_expired(now)
                pending, pending_token = PendingSignIn.start(user.id, address, now)
                await tx.pending_sign_ins.add(pending)
                return SecondFactorAsked(pending_token, pending.expires_at)
            token = await start_session(tx, user, client, now)
        return SignedIn(user, token)

    async def _journal_failure(self, user: User, client: Client) -> None:
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [Event("account.sign_in_failed", None, Actor.system(), {"user_id": str(user.id), "ip": client.ip})]
            )


class SignInWithSecondFactor:
    """The second step of signing in with a password: a code of the authenticator app, or a recovery code.

    The pending sign-in works only from the address its password came from, and opens one session.
    Wrong codes count per account and per address, apart from wrong passwords (sign-in.md, 7).
    """

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], box: SecretBox, postman: Postman) -> None:
        self._uow = uow
        self._box = box
        self._postman = postman

    async def execute(self, *, token: str, proof: SecondFactorProof, client: Client) -> tuple[User, str]:
        """The account and a new session's token."""
        address = address_key(client.ip)
        now = datetime.now(UTC)
        async with self._uow.query() as tx:
            pending = await tx.pending_sign_ins.get(hash_token(token), now)
        if pending is None or pending.address != address:
            raise SecondFactorExpiredError("signing in took too long or was already done: sign in again")
        account = second_factor_key(pending.user_id)
        others = [] if address is None else [address]
        async with self._uow.transaction() as tx:
            await count_attempt(tx, [account, *others], now)
        # Committed before the code is checked, so a wrong one stays counted.
        try:
            return await self._complete(pending, proof, client, account, others)
        except WrongCodeError:
            await self._journal_failure(pending, proof, client)
            raise

    async def _complete(
        self, pending: PendingSignIn, proof: SecondFactorProof, client: Client, account: str, others: list[str]
    ) -> tuple[User, str]:
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            # The account first: two codes checked at once must not both pass as the same code.
            user = await tx.users.get_for_update(pending.user_id)
            totp = None if user is None or user.disabled_at is not None else await totp_enabled(tx, user.id)
            if user is None or totp is None or not await tx.pending_sign_ins.take(pending.id, now):
                raise SecondFactorExpiredError("signing in took too long or was already done: sign in again")
            method = await prove_second_factor(tx, self._box, self._postman, user, totp, proof, now)
            await attempt_succeeded(tx, account, others)
            token = await start_session(tx, user, client, now, second_factor=method)
        return user, token

    async def _journal_failure(self, pending: PendingSignIn, proof: SecondFactorProof, client: Client) -> None:
        method = method_of(proof)
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [
                    Event(
                        "account.sign_in_failed",
                        None,
                        Actor.system(),
                        {"user_id": str(pending.user_id), "ip": client.ip, "second_factor": method.value},
                    )
                ]
            )


class StartPasskeySignIn:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], relying_party: RelyingParty) -> None:
        self._uow = uow
        self._relying_party = relying_party

    async def execute(self, client: Client) -> PasskeyOptions:
        """The options for ``navigator.credentials.get`` that let the person pick any passkey."""
        now = datetime.now(UTC)
        address = address_key(client.ip)
        challenge = Challenge.for_sign_in(address, now)
        async with self._uow.transaction() as tx:
            # A request with no address (through a Unix socket) has nothing to count it by.
            if address is not None:
                check_open_sign_ins(await tx.challenges.open_sign_ins(address, now), now)
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


def _open(session: Session, user: User | None, grant: Grant | None, now: datetime) -> CurrentSession | GuestSession:
    if not session.is_active(now):
        raise UnauthenticatedError("the session has ended; sign in again")
    if user is not None:
        if user.disabled_at is not None:
            raise UnauthenticatedError("the session has ended; sign in again")
        return CurrentSession(id=session.id, user_id=user.id, authenticated_at=session.authenticated_at)
    # A guest's session lasts as long as its link's grant: revoking or expiring it ends the visit at once.
    if grant is None or not grant.is_active(now):
        raise UnauthenticatedError("the guest link has ended")
    return GuestSession(grant_id=grant.id, link_id=grant.principal_id, home_id=grant.home_id)


async def start_session(
    tx: IdentityTransaction,
    user: User,
    client: Client,
    now: datetime,
    *,
    passkey_id: UUID | None = None,
    external_identity_id: UUID | None = None,
    second_factor: SecondFactorMethod | None = None,
) -> str:
    """Open a session for the user in the transaction and journal the sign-in; the token for the cookie.

    ``passkey_id`` names the passkey the person signed in with, ``external_identity_id`` their identity at the
    operator's provider; without either, they used their password, and ``second_factor`` says how they
    confirmed it, if they had to.
    """
    session, token = Session.start(user.id, client, now)
    await tx.sessions.add(session)
    payload = {"user_id": str(user.id), "session_id": str(session.id), "ip": client.ip}
    if passkey_id is not None:
        payload["passkey_id"] = str(passkey_id)
    if external_identity_id is not None:
        payload["external_identity_id"] = str(external_identity_id)
    if second_factor is not None:
        payload["second_factor"] = second_factor.value
    await tx.journal.append([Event("account.signed_in", None, Actor.user(user.id), payload)])
    return token

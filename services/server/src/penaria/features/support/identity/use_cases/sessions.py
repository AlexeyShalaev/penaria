"""Signing in and out, and finding the account behind a request's session."""

from datetime import UTC, datetime

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import UnauthenticatedError
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.accounts import normalize_username
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client, CurrentSession, Session, hash_token
from penaria.features.support.identity.domain.throttle import account_key, address_key
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt


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
        return CurrentSession(id=session.id, user_id=user.id)


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
            if new_hash is not None:
                await tx.passwords.set(user.id, new_hash, now)
            token = await start_session(tx, user, client, now)
        return user, token

    async def _journal_failure(self, user: User, client: Client) -> None:
        async with self._uow.transaction() as tx:
            await tx.journal.append(
                [Event("account.sign_in_failed", None, Actor.system(), {"user_id": str(user.id), "ip": client.ip})]
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


async def start_session(tx: IdentityTransaction, user: User, client: Client, now: datetime) -> str:
    """Open a session for the user in the transaction and journal the sign-in; the token for the cookie."""
    session, token = Session.start(user.id, client, now)
    await tx.sessions.add(session)
    await tx.journal.append(
        [
            Event(
                "account.signed_in",
                None,
                Actor.user(user.id),
                {"user_id": str(user.id), "session_id": str(session.id), "ip": client.ip},
            )
        ]
    )
    return token

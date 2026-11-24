"""The signed-in person's own account: their profile, password and sessions."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.errors import InvalidError, NotFoundError
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.accounts import check_display_name, check_locale, check_password
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession, Session
from penaria.features.support.identity.domain.throttle import account_key
from penaria.features.support.identity.use_cases.attempts import attempt_succeeded, count_attempt


class SessionNotFoundError(NotFoundError):
    code = "session_not_found"


class WrongPasswordError(InvalidError):
    code = "wrong_password"


class GetAccount:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> User:
        async with self._uow.query() as tx:
            return await _load(tx, current)


class UpdateAccount:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, *, display_name: str | None, locale: str | None) -> User:
        new_name = None if display_name is None else check_display_name(display_name)
        new_locale = None if locale is None else check_locale(locale)
        async with self._uow.transaction() as tx:
            user = await tx.users.get_for_update(current.user_id)
            if user is None:
                raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
            changes: dict[str, str] = {}
            if new_name is not None and new_name != user.display_name:
                user.display_name = changes["display_name"] = new_name
            if new_locale is not None and new_locale != user.locale:
                user.locale = changes["locale"] = new_locale
            if changes:
                await tx.users.save(user)
                await tx.journal.append(
                    [Event("account.updated", None, Actor.user(user.id), {"user_id": str(user.id), **changes})]
                )
        return user


class ChangePassword:
    """A new password for someone who knows the current one; every other session of theirs ends."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(self, current: CurrentSession, *, current_password: str, new_password: str) -> None:
        check_password(new_password)
        async with self._uow.transaction() as tx:
            user = await _load(tx, current)
            if user.username is None:
                raise RuntimeError(f"the user ({user.id}) of an open session has no username")
            # Guessing the current password from a stolen session is limited like signing in.
            account = account_key(user.username)
            await count_attempt(tx, [account], datetime.now(UTC))
            password_hash = await tx.passwords.get(user.id)
        if not await self._hasher.verify(password_hash, current_password):
            raise WrongPasswordError("the current password is wrong")
        new_hash = await self._hasher.hash(new_password)
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            await attempt_succeeded(tx, account)
            await tx.passwords.set(user.id, new_hash, now)
            revoked = await tx.sessions.revoke_all_but(user.id, current.id, now)
            await tx.journal.append(
                [
                    Event(
                        "account.password_changed",
                        None,
                        Actor.user(user.id),
                        {"user_id": str(user.id), "sessions_ended": len(revoked)},
                    ),
                    *_revoked_events(current, revoked),
                ]
            )


class ListSessions:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> list[Session]:
        """The account's open sessions, the most recently used first."""
        async with self._uow.query() as tx:
            return await tx.sessions.active_for(current.user_id, datetime.now(UTC))


class RevokeSession:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession, session_id: UUID) -> None:
        async with self._uow.transaction() as tx:
            if not await tx.sessions.revoke(current.user_id, session_id, datetime.now(UTC)):
                raise SessionNotFoundError(params={"session_id": str(session_id)})
            await tx.journal.append(_revoked_events(current, [session_id]))


class RevokeOtherSessions:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, current: CurrentSession) -> int:
        """End every session of the account but the current one; how many ended."""
        async with self._uow.transaction() as tx:
            revoked = await tx.sessions.revoke_all_but(current.user_id, current.id, datetime.now(UTC))
            await tx.journal.append(_revoked_events(current, revoked))
        return len(revoked)


async def _load(tx: IdentityTransaction, current: CurrentSession) -> User:
    user = await tx.users.get(current.user_id)
    if user is None:
        raise RuntimeError(f"the user ({current.user_id}) of an open session does not exist")
    return user


def _revoked_events(current: CurrentSession, session_ids: list[UUID]) -> list[Event]:
    return [
        Event(
            "session.revoked",
            None,
            Actor.user(current.user_id),
            {"user_id": str(current.user_id), "session_id": str(session_id)},
        )
        for session_id in session_ids
    ]

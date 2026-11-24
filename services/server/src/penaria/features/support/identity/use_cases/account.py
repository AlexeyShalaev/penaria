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
from penaria.features.support.identity.domain.throttle import FAILURES_EXPIRE_AFTER, account_key, check_not_blocked


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
        changes: dict[str, str] = {}
        if display_name is not None:
            changes["display_name"] = check_display_name(display_name)
        if locale is not None:
            changes["locale"] = check_locale(locale)
        async with self._uow.transaction() as tx:
            user = await _load(tx, current)
            if "display_name" in changes:
                user.display_name = changes["display_name"]
            if "locale" in changes:
                user.locale = changes["locale"]
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
        new_hash = await self._hasher.hash(new_password)
        async with self._uow.transaction() as tx:
            user = await _load(tx, current)
            # Guessing the current password from a stolen session is limited like signing in.
            if user.username is None:
                raise RuntimeError(f"the user ({user.id}) of an open session has no username")
            keys = [account_key(user.username)]
            await tx.failures.lock(keys)
            now = datetime.now(UTC)
            check_not_blocked(await tx.failures.get(keys), now)
            matches = await self._hasher.verify(await tx.passwords.get(user.id), current_password)
            if matches:
                await tx.failures.clear(keys[0])
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
            else:
                await tx.failures.record(keys, now, forget_before=now - FAILURES_EXPIRE_AFTER)
        # Raised after the transaction, so the failure it counted is kept.
        if not matches:
            raise WrongPasswordError("the current password is wrong")


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

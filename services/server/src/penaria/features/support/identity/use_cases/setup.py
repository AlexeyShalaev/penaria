"""The first start: a token from the server's log lets the first person create the install's admin account."""

from datetime import UTC, datetime

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.identity.domain.accounts import (
    check_display_name,
    check_locale,
    check_password,
    check_username,
)
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import Client
from penaria.features.support.identity.domain.setup import (
    AlreadySetUpError,
    InvalidSetupTokenError,
    new_setup_token,
    setup_token_matches,
)
from penaria.features.support.identity.domain.throttle import (
    FAILURES_EXPIRE_AFTER,
    address_key,
    check_not_blocked,
)
from penaria.features.support.identity.use_cases.sessions import start_session


class NeedsSetup:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self) -> bool:
        """Whether no account can sign in yet."""
        async with self._uow.query() as tx:
            return not await tx.passwords.any()


class IssueSetupToken:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self) -> str | None:
        """A new setup token, replacing any earlier one, while the install needs setup; otherwise None."""
        async with self._uow.transaction() as tx:
            if await tx.passwords.any():
                return None
            token, token_hash = new_setup_token()
            await tx.setup_tokens.replace(token_hash, datetime.now(UTC))
        return token


class CompleteSetup:
    """Make the install's first account: the local user from before sign-in, with its homes, or a new one."""

    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction], hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(
        self, *, token: str, username: str, display_name: str, password: str, locale: str, client: Client
    ) -> tuple[User, str]:
        """The account and a session's token for it."""
        username = check_username(username)
        display_name = check_display_name(display_name)
        locale = check_locale(locale)
        check_password(password)
        password_hash = await self._hasher.hash(password)
        address = address_key(client.ip)
        async with self._uow.transaction() as tx:
            # Locks the token: of two attempts at once, the second sees the install set up.
            stored = await tx.setup_tokens.current_for_update()
            if await tx.passwords.any():
                raise AlreadySetUpError("the install is already set up; sign in instead")
            now = datetime.now(UTC)
            if address is not None:
                check_not_blocked(await tx.failures.get([address]), now)
            if setup_token_matches(token, stored):
                user = await self._make_account(tx, username, display_name, locale)
                await tx.passwords.set(user.id, password_hash, now)
                await tx.setup_tokens.clear()
                await tx.journal.append(
                    [Event("account.setup_completed", None, Actor.user(user.id), {"user_id": str(user.id)})]
                )
                return user, await start_session(tx, user, client, now)
            if address is not None:
                await tx.failures.record([address], now, forget_before=now - FAILURES_EXPIRE_AFTER)
        raise InvalidSetupTokenError("wrong setup token; take the one from the server's latest log")

    async def _make_account(self, tx: IdentityTransaction, username: str, display_name: str, locale: str) -> User:
        user = await tx.users.first()
        if user is None:
            user = User(display_name=display_name, locale=locale, username=username, install_admin=True)
            await tx.users.add(user)
            return user
        user.username = username
        user.display_name = display_name
        user.locale = locale
        user.install_admin = True
        await tx.users.save(user)
        return user

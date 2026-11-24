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
from penaria.features.support.identity.domain.throttle import address_key
from penaria.features.support.identity.use_cases.attempts import count_attempt
from penaria.features.support.identity.use_cases.sessions import start_session


class NeedsSetup:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self) -> bool:
        """Whether no account can sign in yet."""
        async with self._uow.query() as tx:
            return not await tx.users.any_account()


class IssueSetupToken:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self) -> str | None:
        """A new setup token, replacing any earlier one, while the install needs setup; otherwise None."""
        async with self._uow.transaction() as tx:
            await tx.setup_tokens.lock()
            if await tx.users.any_account():
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
        address = address_key(client.ip)
        attempts = [] if address is None else [address]
        async with self._uow.transaction() as tx:
            # Of two attempts at once, the second waits here and then sees the install set up.
            await tx.setup_tokens.lock()
            if await tx.users.any_account():
                raise AlreadySetUpError("the install is already set up; sign in instead")
            now = datetime.now(UTC)
            await count_attempt(tx, attempts, now)
            matches = setup_token_matches(token, await tx.setup_tokens.current())
        # Committed before refusing, so a wrong token stays counted.
        if not matches:
            raise InvalidSetupTokenError("wrong setup token; take the one from the server's latest log")
        password_hash = await self._hasher.hash(password)
        async with self._uow.transaction() as tx:
            # Checked again: another replica may have completed or restarted the setup meanwhile.
            await tx.setup_tokens.lock()
            if await tx.users.any_account():
                raise AlreadySetUpError("the install is already set up; sign in instead")
            if not setup_token_matches(token, await tx.setup_tokens.current()):
                raise InvalidSetupTokenError("wrong setup token; take the one from the server's latest log")
            await tx.failures.uncount(attempts)
            user = await self._make_account(tx, username, display_name, locale)
            await tx.passwords.set(user.id, password_hash, now)
            await tx.setup_tokens.clear()
            await tx.journal.append(
                [Event("account.setup_completed", None, Actor.user(user.id), {"user_id": str(user.id)})]
            )
            return user, await start_session(tx, user, client, now)

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

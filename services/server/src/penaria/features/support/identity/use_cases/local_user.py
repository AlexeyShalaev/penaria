"""The one local user every request acts as, until sign-in lands (its own design comes first)."""

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.repositories import IdentityTransaction


class EnsureLocalUser:
    def __init__(self, uow: AsyncUnitOfWork[IdentityTransaction]) -> None:
        self._uow = uow

    async def execute(self, *, locale: str = "en") -> User:
        async with self._uow.transaction() as tx:
            user = await tx.users.first()
            if user is None:
                user = User(display_name="Owner", locale=locale)
                await tx.users.add(user)
        return user

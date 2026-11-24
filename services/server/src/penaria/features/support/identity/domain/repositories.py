"""What the identity use cases need from storage."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from penaria.features.shared.journal import Journal
from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, Role, User


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def first(self) -> User | None:
        """The earliest user, if there is any."""
        ...


class HomeRepository(Protocol):
    async def add(self, home: Home) -> None: ...

    async def get(self, home_id: UUID) -> Home | None: ...

    async def with_grants_for(self, principal_type: PrincipalType, principal_id: UUID, now: datetime) -> list[Home]:
        """The homes where the principal holds an active grant, by name."""
        ...


class RoleRepository(Protocol):
    async def add_all(self, roles: Sequence[Role]) -> None: ...


class GrantRepository(Protocol):
    async def add(self, grant: Grant) -> None: ...

    async def applicable(
        self,
        principal_type: PrincipalType,
        principal_id: UUID,
        home_id: UUID,
        path: Sequence[UUID],
        now: datetime,
    ) -> list[Role]:
        """The roles of the principal's active grants whose scope is the whole home or an id in ``path``."""
        ...


class IdentityTransaction(Protocol):
    @property
    def users(self) -> UserRepository: ...

    @property
    def homes(self) -> HomeRepository: ...

    @property
    def roles(self) -> RoleRepository: ...

    @property
    def grants(self) -> GrantRepository: ...

    @property
    def journal(self) -> Journal: ...

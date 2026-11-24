"""One transaction class for every context; each use case sees it through its own protocol."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUowTransaction

from penaria.features.core.registry.infra.repository import PostgresEntityRepository
from penaria.features.support.identity.infra.repositories import (
    PostgresGrantRepository,
    PostgresHomeRepository,
    PostgresRoleRepository,
    PostgresUserRepository,
)
from penaria.features.support.platform.infra.journal import PostgresJournal


class PenariaTransaction(AsyncSQLAlchemyUowTransaction):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._users = PostgresUserRepository(session)
        self._homes = PostgresHomeRepository(session)
        self._roles = PostgresRoleRepository(session)
        self._grants = PostgresGrantRepository(session)
        self._entities = PostgresEntityRepository(session)
        self._journal = PostgresJournal(session)

    @property
    def users(self) -> PostgresUserRepository:
        return self._users

    @property
    def homes(self) -> PostgresHomeRepository:
        return self._homes

    @property
    def roles(self) -> PostgresRoleRepository:
        return self._roles

    @property
    def grants(self) -> PostgresGrantRepository:
        return self._grants

    @property
    def entities(self) -> PostgresEntityRepository:
        return self._entities

    @property
    def journal(self) -> PostgresJournal:
        return self._journal

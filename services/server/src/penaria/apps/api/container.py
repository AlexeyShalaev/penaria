"""The DI container of the API process."""

from typing import cast

from dishka import Provider, Scope, make_async_container, provide, provide_all
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy_foundation_kit import (
    AsyncSQLAlchemyUnitOfWork,
    AsyncUnitOfWork,
    PostgresMetricsProtocol,
    PostgresSettingsProtocol,
)
from sqlalchemy_foundation_kit.contrib.di import AsyncDatabaseProvider

from penaria.apps.api.settings import Settings
from penaria.features.core.registry.domain.repositories import RegistryTransaction
from penaria.features.core.registry.use_cases.access import EntityAccess
from penaria.features.core.registry.use_cases.commands import (
    ArchiveEntity,
    CreateEntity,
    MoveEntity,
    RestoreEntity,
    UpdateEntity,
    VerifyEntity,
)
from penaria.features.core.registry.use_cases.queries import EntityHistory, GetEntity, ListChildren
from penaria.features.shared.access import AccessPolicy
from penaria.features.shared.actor import Actor
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.use_cases.access import GrantAccessPolicy
from penaria.features.support.identity.use_cases.homes import CreateHome, GetHome, ListHomes
from penaria.features.support.identity.use_cases.local_user import EnsureLocalUser
from penaria.integrations.postgres.transaction import PenariaTransaction


class SettingsProvider(Provider):
    scope = Scope.APP

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @provide
    def database(self) -> PostgresSettingsProtocol:
        # The kit's protocol declares its attributes invariantly, so its own settings model does
        # not match it structurally.
        return cast(PostgresSettingsProtocol, self._settings.database)

    @provide
    def database_metrics(self) -> PostgresMetricsProtocol | None:
        # dishka resolves an optional dependency by its annotation, so "no metrics" is provided too.
        return None


class UnitOfWorkProvider(Provider):
    """One unit of work, seen by each context through its own transaction protocol."""

    scope = Scope.APP

    @provide
    def uow(self, session_maker: async_sessionmaker[AsyncSession]) -> AsyncSQLAlchemyUnitOfWork[PenariaTransaction]:
        return AsyncSQLAlchemyUnitOfWork(session_maker, transaction_factory=PenariaTransaction)

    @provide
    def identity(self, uow: AsyncSQLAlchemyUnitOfWork[PenariaTransaction]) -> AsyncUnitOfWork[IdentityTransaction]:
        return uow

    @provide
    def registry(self, uow: AsyncSQLAlchemyUnitOfWork[PenariaTransaction]) -> AsyncUnitOfWork[RegistryTransaction]:
        return uow


class UseCaseProvider(Provider):
    scope = Scope.APP

    access_policy = provide(GrantAccessPolicy, provides=AccessPolicy)
    use_cases = provide_all(
        EnsureLocalUser,
        CreateHome,
        ListHomes,
        GetHome,
        EntityAccess,
        CreateEntity,
        UpdateEntity,
        MoveEntity,
        ArchiveEntity,
        RestoreEntity,
        VerifyEntity,
        GetEntity,
        ListChildren,
        EntityHistory,
    )

    @provide
    async def actor(self, ensure_local_user: EnsureLocalUser) -> Actor:
        # Until sign-in lands every request acts as the one local user.
        return Actor.user((await ensure_local_user.execute()).id)


def build_container(settings: Settings) -> DishkaContainer:
    return DishkaContainer(
        make_async_container(
            SettingsProvider(settings), AsyncDatabaseProvider(), UnitOfWorkProvider(), UseCaseProvider()
        )
    )

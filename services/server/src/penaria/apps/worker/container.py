"""The DI container of the worker process."""

from collections.abc import AsyncIterator
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

from penaria.apps.worker.settings import Settings
from penaria.features.shared.homes import HomeTimezones
from penaria.features.support.documents.domain.processing import Renderer
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.domain.storage import ObjectStorage
from penaria.features.support.documents.infra.sandbox import SandboxRenderer
from penaria.features.support.documents.use_cases.processing import ProcessNextFile
from penaria.features.support.documents.use_cases.sweep import SweepFiles
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.use_cases.homes import IdentityHomeTimezones
from penaria.integrations.postgres.transaction import PenariaTransaction
from penaria.integrations.s3.storage import open_s3


class WorkerProvider(Provider):
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
        return None

    @provide
    async def storage(self) -> AsyncIterator[ObjectStorage]:
        if self._settings.s3 is None:
            raise RuntimeError("without PENARIA_S3__* the worker idles and never asks for the storage")
        async with open_s3(self._settings.s3) as storage:
            yield storage

    @provide
    def renderer(self) -> Renderer:
        return SandboxRenderer()

    @provide
    def uow(self, session_maker: async_sessionmaker[AsyncSession]) -> AsyncSQLAlchemyUnitOfWork[PenariaTransaction]:
        return AsyncSQLAlchemyUnitOfWork(session_maker, transaction_factory=PenariaTransaction)

    @provide
    def documents(self, uow: AsyncSQLAlchemyUnitOfWork[PenariaTransaction]) -> AsyncUnitOfWork[DocumentsTransaction]:
        return uow

    @provide
    def identity(self, uow: AsyncSQLAlchemyUnitOfWork[PenariaTransaction]) -> AsyncUnitOfWork[IdentityTransaction]:
        return uow

    home_timezones = provide(IdentityHomeTimezones, provides=HomeTimezones)
    use_cases = provide_all(ProcessNextFile, SweepFiles)


def build_container(settings: Settings) -> DishkaContainer:
    return DishkaContainer(make_async_container(WorkerProvider(settings), AsyncDatabaseProvider()))

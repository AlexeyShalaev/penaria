"""The DI container of the API process."""

from typing import cast

from dishka import Provider, Scope, make_async_container, provide
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy_foundation_kit import PostgresMetricsProtocol, PostgresSettingsProtocol
from sqlalchemy_foundation_kit.contrib.di import AsyncDatabaseProvider, AsyncUnitOfWorkProvider

from penaria.apps.api.settings import Settings


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


def build_container(settings: Settings) -> DishkaContainer:
    return DishkaContainer(
        make_async_container(SettingsProvider(settings), AsyncDatabaseProvider(), AsyncUnitOfWorkProvider())
    )

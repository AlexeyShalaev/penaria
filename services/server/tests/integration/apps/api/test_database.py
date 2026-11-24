import pytest
from servicewright.adapters.fastapi import HttpServerSettings
from sqlalchemy import text
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUowTransaction, AsyncUnitOfWork

from penaria.apps.api.container import build_container
from penaria.apps.api.entrypoint import build_spec
from penaria.apps.api.settings import Settings
from penaria.common.database import DatabaseSettings

pytestmark = pytest.mark.integration


def make_settings(database: DatabaseSettings) -> Settings:
    return Settings.model_validate({"server": HttpServerSettings(), "database": database})


async def test_the_unit_of_work_reaches_the_database(database_settings: DatabaseSettings) -> None:
    container = build_container(make_settings(database_settings))
    async with container.app_scope() as app_scope:
        uow = await app_scope.get(AsyncUnitOfWork[AsyncSQLAlchemyUowTransaction])  # type: ignore[type-abstract]
        async with uow.transaction() as tx:
            answer = await tx.session.scalar(text("SELECT 41 + 1"))

    assert answer == 42


async def test_readiness_follows_the_database(database_settings: DatabaseSettings) -> None:
    spec = build_spec()
    container = build_container(make_settings(database_settings))
    async with container.app_scope() as app_scope:
        await spec.lifecycle.run_pre_start_hooks(app_scope)
        spec.health.ready = True

        report = await spec.health.readiness()

    assert report.checks == {"postgres": True}
    assert report.healthy

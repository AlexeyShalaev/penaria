import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import text
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.apps.api.entrypoint import build_spec
from penaria.integrations.postgres.transaction import PenariaTransaction

pytestmark = pytest.mark.integration


async def test_the_unit_of_work_reaches_the_database(container: DishkaContainer) -> None:
    async with container.app_scope() as app_scope:
        uow = await app_scope.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])
        async with uow.transaction() as tx:
            answer = await tx.session.scalar(text("SELECT 41 + 1"))

    assert answer == 42


async def test_readiness_follows_the_database(container: DishkaContainer) -> None:
    spec = build_spec()
    async with container.app_scope() as app_scope:
        await spec.lifecycle.run_pre_start_hooks(app_scope)
        spec.health.ready = True

        report = await spec.health.readiness()

    assert report.checks == {"postgres": True}
    assert report.healthy

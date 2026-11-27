"""The service spec and the daemon of the worker process."""

import asyncio

from servicewright import AppSpec
from servicewright.adapters.builtin import DaemonEntrypoint
from servicewright.adapters.dishka import DishkaContainer
from servicewright.adapters.health.postgres import PostgresHealthCheck
from servicewright.core.contracts import AppScopeProtocol, UnitScopeProtocol
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from penaria.apps.worker.container import build_container
from penaria.apps.worker.loop import idle, process_files
from penaria.apps.worker.settings import Settings
from penaria.features.support.documents.use_cases.processing import ProcessNextFile
from penaria.features.support.documents.use_cases.sweep import SweepFiles

SERVICE_NAME = "penaria-worker"


def build_spec() -> AppSpec[Settings, DishkaContainer]:
    spec = AppSpec(service_name=SERVICE_NAME, create_container=build_container)

    async def check_database(app_scope: AppScopeProtocol | None = None) -> None:
        # Resolving the session maker connects, retrying while the database starts.
        if app_scope is None:
            raise RuntimeError("the host runs pre-start hooks inside the application scope")
        session_maker = await app_scope.get(async_sessionmaker[AsyncSession])
        spec.health.add_check("postgres", PostgresHealthCheck(session_maker))

    spec.lifecycle.add_pre_start_hook(check_database)
    return spec


def build_daemon(settings: Settings) -> DaemonEntrypoint:
    async def work(scope: UnitScopeProtocol, stop: asyncio.Event) -> None:
        if settings.s3 is None:
            await idle(stop)
        else:
            await process_files(await scope.get(ProcessNextFile), await scope.get(SweepFiles), stop)

    return DaemonEntrypoint(work, kind="files")

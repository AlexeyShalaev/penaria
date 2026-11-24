"""The service spec and the HTTP entrypoint of the API process."""

from servicewright import AppSpec
from servicewright.adapters.dishka import DishkaContainer
from servicewright.adapters.fastapi import FastApiEntrypoint
from servicewright.adapters.health.postgres import PostgresHealthCheck
from servicewright.core.contracts import AppScopeProtocol
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from penaria import __version__
from penaria.apps.api.container import build_container
from penaria.apps.api.settings import Settings
from penaria.features.core.registry.api.routes import router as registry_router
from penaria.features.shared.actor import Actor
from penaria.features.support.identity.api.routes import router as identity_router

SERVICE_NAME = "penaria-api"


def build_spec() -> AppSpec[Settings, DishkaContainer]:
    spec = AppSpec(service_name=SERVICE_NAME, create_container=build_container)

    async def check_database(app_scope: AppScopeProtocol | None = None) -> None:
        # Resolving the session maker connects, retrying while the database starts; from then
        # on readiness follows the database.
        if app_scope is None:
            raise RuntimeError("the host runs pre-start hooks inside the application scope")
        session_maker = await app_scope.get(async_sessionmaker[AsyncSession])
        spec.health.add_check("postgres", PostgresHealthCheck(session_maker))
        # The local user exists before the first request.
        await app_scope.get(Actor)

    spec.lifecycle.add_pre_start_hook(check_database)
    return spec


def build_http(settings: Settings) -> FastApiEntrypoint:
    return FastApiEntrypoint(
        config=settings.server.to_config(version=__version__), routers=(identity_router, registry_router)
    )

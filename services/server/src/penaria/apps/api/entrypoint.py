"""The service spec and the HTTP entrypoint of the API process."""

import dataclasses
import logging

from fastapi import Depends
from servicewright import AppSpec
from servicewright.adapters.dishka import DishkaContainer
from servicewright.adapters.fastapi import FastApiEntrypoint
from servicewright.adapters.health.postgres import PostgresHealthCheck
from servicewright.core.contracts import AppScopeProtocol
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from penaria import __version__
from penaria.apps.api.container import build_container
from penaria.apps.api.origin import origin_check
from penaria.apps.api.settings import Settings
from penaria.features.core.registry.api.routes import router as registry_router
from penaria.features.support.identity.api.account import router as account_router
from penaria.features.support.identity.api.account import sign_in_router
from penaria.features.support.identity.api.passkeys import router as passkeys_router
from penaria.features.support.identity.api.passkeys import sign_in_router as passkey_sign_in_router
from penaria.features.support.identity.api.routes import router as identity_router
from penaria.features.support.identity.use_cases.setup import IssueSetupToken

SERVICE_NAME = "penaria-api"
ROUTERS = (
    sign_in_router,
    passkey_sign_in_router,
    account_router,
    passkeys_router,
    identity_router,
    registry_router,
)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})

logger = logging.getLogger(__name__)


def build_spec() -> AppSpec[Settings, DishkaContainer]:
    spec = AppSpec(service_name=SERVICE_NAME, create_container=build_container)

    async def check_database(app_scope: AppScopeProtocol | None = None) -> None:
        # Resolving the session maker connects, retrying while the database starts; from then
        # on readiness follows the database.
        if app_scope is None:
            raise RuntimeError("the host runs pre-start hooks inside the application scope")
        session_maker = await app_scope.get(async_sessionmaker[AsyncSession])
        spec.health.add_check("postgres", PostgresHealthCheck(session_maker))

    async def offer_setup(app_scope: AppScopeProtocol | None = None) -> None:
        if app_scope is None:
            raise RuntimeError("the host runs pre-start hooks inside the application scope")
        token = await (await app_scope.get(IssueSetupToken)).execute()
        if token is not None:
            # The one place the token is shown: whoever reads the server's log owns the machine.
            logger.warning("Penaria needs setup: open it in a browser and enter the setup token %s", token)

    spec.lifecycle.add_pre_start_hook(check_database)
    spec.lifecycle.add_pre_start_hook(offer_setup)
    return spec


def build_http(settings: Settings) -> FastApiEntrypoint:
    if not settings.serves_https and settings.public_url.host not in LOOPBACK_HOSTS:
        logger.warning(
            "PENARIA_PUBLIC_URL is plain HTTP: passwords and session cookies cross the network unencrypted; "
            "put Penaria behind HTTPS"
        )
    config = settings.server.to_config(version=__version__)
    # Every route, the public ones included, refuses a change asked for by another site.
    config = dataclasses.replace(
        config,
        fastapi_kwargs={**config.fastapi_kwargs, "dependencies": [Depends(origin_check(settings.public_origin))]},
    )
    return FastApiEntrypoint(config=config, routers=ROUTERS)

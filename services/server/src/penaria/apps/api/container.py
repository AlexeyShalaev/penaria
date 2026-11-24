"""The DI container of the API process."""

import contextlib
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

from dishka import Provider, Scope, from_context, make_async_container, provide, provide_all
from fastapi import Request
from servicewright.adapters.dishka import DishkaContainer, DishkaScope
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
from penaria.features.support.identity.api.cookies import SESSION_COOKIE, SessionCookie
from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.repositories import IdentityTransaction
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.infra.argon2 import Argon2PasswordHasher
from penaria.features.support.identity.use_cases.access import GrantAccessPolicy
from penaria.features.support.identity.use_cases.account import (
    ChangePassword,
    GetAccount,
    ListSessions,
    RevokeOtherSessions,
    RevokeSession,
    UpdateAccount,
)
from penaria.features.support.identity.use_cases.homes import CreateHome, GetHome, ListHomes
from penaria.features.support.identity.use_cases.sessions import Authenticate, SignIn, SignOut
from penaria.features.support.identity.use_cases.setup import CompleteSetup, IssueSetupToken, NeedsSetup
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

    @provide
    def session_cookie(self) -> SessionCookie:
        return SessionCookie(secure=self._settings.public_url.scheme == "https")


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
    password_hasher = provide(Argon2PasswordHasher, provides=PasswordHasher)
    use_cases = provide_all(
        NeedsSetup,
        IssueSetupToken,
        CompleteSetup,
        Authenticate,
        SignIn,
        SignOut,
        GetAccount,
        UpdateAccount,
        ChangePassword,
        ListSessions,
        RevokeSession,
        RevokeOtherSessions,
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


class RequestProvider(Provider):
    """Who makes the request: resolved once per request, from its session cookie."""

    scope = Scope.REQUEST

    request = from_context(provides=Request)

    @provide
    async def current_session(self, request: Request, authenticate: Authenticate) -> CurrentSession:
        return await authenticate.execute(request.cookies.get(SESSION_COOKIE))

    @provide
    def actor(self, session: CurrentSession) -> Actor:
        return Actor.user(session.user_id)


class ApiContainer(DishkaContainer):
    """servicewright hands a request's scope the request under the key "request"; dishka finds context by type."""

    @contextlib.asynccontextmanager
    async def unit_scope(self, context: Mapping[Any, Any] | None = None) -> AsyncIterator[DishkaScope]:
        request = None if context is None else context.get("request")
        if request is not None:
            context = {**context, Request: request}  # type: ignore[dict-item]
        async with super().unit_scope(context) as scope:
            yield scope


def build_container(settings: Settings) -> DishkaContainer:
    return ApiContainer(
        make_async_container(
            SettingsProvider(settings),
            AsyncDatabaseProvider(),
            UnitOfWorkProvider(),
            UseCaseProvider(),
            RequestProvider(),
        )
    )

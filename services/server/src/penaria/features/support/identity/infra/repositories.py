"""PostgreSQL repositories of the identity context."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, Role, User
from penaria.features.support.identity.domain.permissions import Preset
from penaria.features.support.identity.infra.orm import GrantDB, HomeDB, RoleDB, UserDB


class PostgresUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(UserDB(id=user.id, display_name=user.display_name, locale=user.locale))

    async def first(self) -> User | None:
        row = await self._session.scalar(select(UserDB).order_by(UserDB.id).limit(1))
        return None if row is None else User(id=row.id, display_name=row.display_name, locale=row.locale)


class PostgresHomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, home: Home) -> None:
        self._session.add(
            HomeDB(id=home.id, name=home.name, timezone=home.timezone, locale=home.locale, version=home.version)
        )
        # Without ORM relationships the session does not order inserts by foreign keys: rows that
        # others reference are written at once.
        await self._session.flush()

    async def get(self, home_id: UUID) -> Home | None:
        row = await self._session.get(HomeDB, home_id)
        return None if row is None else _home(row)

    async def with_grants_for(self, principal_type: PrincipalType, principal_id: UUID, now: datetime) -> list[Home]:
        granted = select(GrantDB.home_id).where(
            GrantDB.principal_type == principal_type.value,
            GrantDB.principal_id == principal_id,
            *_active(now),
        )
        rows = await self._session.scalars(select(HomeDB).where(HomeDB.id.in_(granted)).order_by(HomeDB.name))
        return [_home(row) for row in rows]


class PostgresRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, roles: Sequence[Role]) -> None:
        self._session.add_all(
            [
                RoleDB(
                    id=role.id,
                    home_id=role.home_id,
                    preset=role.preset.value if role.preset else None,
                    name=role.name,
                    all_permissions=role.all_permissions,
                    permissions=sorted(role.permissions),
                    guest_view=role.guest_view,
                    expiry_required=role.expiry_required,
                    default_duration=role.default_duration,
                )
                for role in roles
            ]
        )
        await self._session.flush()


class PostgresGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, grant: Grant) -> None:
        self._session.add(
            GrantDB(
                id=grant.id,
                home_id=grant.home_id,
                principal_type=grant.principal_type.value,
                principal_id=grant.principal_id,
                role_id=grant.role_id,
                scope_entity_id=grant.scope_entity_id,
                expires_at=grant.expires_at,
                revoked_at=grant.revoked_at,
                created_at=grant.created_at,
            )
        )

    async def applicable(
        self,
        principal_type: PrincipalType,
        principal_id: UUID,
        home_id: UUID,
        path: Sequence[UUID],
        now: datetime,
    ) -> list[Role]:
        scope: ColumnElement[bool] = GrantDB.scope_entity_id.is_(None)
        if path:
            scope = or_(scope, GrantDB.scope_entity_id.in_(list(path)))
        rows = await self._session.scalars(
            select(RoleDB)
            .join(GrantDB, GrantDB.role_id == RoleDB.id)
            .where(
                GrantDB.home_id == home_id,
                GrantDB.principal_type == principal_type.value,
                GrantDB.principal_id == principal_id,
                scope,
                *_active(now),
            )
        )
        return [_role(row) for row in rows]


def _active(now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (GrantDB.revoked_at.is_(None), or_(GrantDB.expires_at.is_(None), GrantDB.expires_at > now))


def _home(row: HomeDB) -> Home:
    return Home(id=row.id, name=row.name, timezone=row.timezone, locale=row.locale, version=row.version)


def _role(row: RoleDB) -> Role:
    return Role(
        id=row.id,
        home_id=row.home_id,
        preset=Preset(row.preset) if row.preset else None,
        name=row.name,
        all_permissions=row.all_permissions,
        permissions=frozenset(row.permissions),
        guest_view=row.guest_view,
        expiry_required=row.expiry_required,
        default_duration=row.default_duration,
    )

"""PostgreSQL repositories of the identity context."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from penaria.features.support.identity.domain.models import Grant, Home, PrincipalType, Role, User
from penaria.features.support.identity.domain.passkeys import Ceremony, Challenge, Passkey
from penaria.features.support.identity.domain.permissions import Preset
from penaria.features.support.identity.domain.sessions import ABSOLUTE_LIFETIME, IDLE_TIMEOUT, Client, Session
from penaria.features.support.identity.domain.throttle import Failures
from penaria.features.support.identity.infra.orm import (
    GrantDB,
    HomeDB,
    PasskeyChallengeDB,
    PasskeyDB,
    PasswordDB,
    RoleDB,
    SessionDB,
    SetupTokenDB,
    SignInFailureDB,
    UserDB,
)

# Any constant works, other than the migrations' (migrations/env.py); "PSET".
SETUP_LOCK_KEY = 0x50534554


class PostgresUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(UserDB(id=user.id, **_user_fields(user)))
        # Passwords and sessions reference the row; see PostgresHomeRepository.add.
        await self._session.flush()

    async def save(self, user: User) -> None:
        await self._session.execute(update(UserDB).where(UserDB.id == user.id).values(**_user_fields(user)))

    async def get(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserDB, user_id)
        return None if row is None else _user(row)

    async def get_for_update(self, user_id: UUID) -> User | None:
        row = await self._session.scalar(select(UserDB).where(UserDB.id == user_id).with_for_update())
        return None if row is None else _user(row)

    async def by_username(self, username: str) -> User | None:
        row = await self._session.scalar(select(UserDB).where(UserDB.username == username))
        return None if row is None else _user(row)

    async def first(self) -> User | None:
        row = await self._session.scalar(select(UserDB).order_by(UserDB.id).limit(1))
        return None if row is None else _user(row)

    async def any_account(self) -> bool:
        return bool(await self._session.scalar(select(exists().where(UserDB.username.is_not(None)))))


class PostgresPasswordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> str | None:
        return await self._session.scalar(select(PasswordDB.hash).where(PasswordDB.user_id == user_id))

    async def set(self, user_id: UUID, password_hash: str, now: datetime) -> None:
        statement = insert(PasswordDB).values(user_id=user_id, hash=password_hash, changed_at=now)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[PasswordDB.user_id], set_={"hash": password_hash, "changed_at": now}
            )
        )


class PostgresSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: Session) -> None:
        self._session.add(
            SessionDB(
                id=session.id,
                token_hash=session.token_hash,
                user_id=session.user_id,
                created_at=session.created_at,
                last_seen_at=session.last_seen_at,
                authenticated_at=session.authenticated_at,
                user_agent=session.client.user_agent,
                ip=session.client.ip,
                revoked_at=session.revoked_at,
            )
        )

    async def by_token_hash(self, token_hash: bytes) -> tuple[Session, User] | None:
        row = (
            await self._session.execute(
                select(SessionDB, UserDB)
                .join(UserDB, UserDB.id == SessionDB.user_id)
                .where(SessionDB.token_hash == token_hash)
            )
        ).one_or_none()
        return None if row is None else (_session(row[0]), _user(row[1]))

    async def active_for(self, user_id: UUID, now: datetime) -> list[Session]:
        rows = await self._session.scalars(
            select(SessionDB)
            .where(SessionDB.user_id == user_id, *_active_session(now))
            .order_by(SessionDB.last_seen_at.desc(), SessionDB.id)
        )
        return [_session(row) for row in rows]

    async def touch(self, session_id: UUID, now: datetime) -> None:
        await self._session.execute(update(SessionDB).where(SessionDB.id == session_id).values(last_seen_at=now))

    async def revoke(self, user_id: UUID, session_id: UUID, now: datetime) -> bool:
        revoked = await self._session.scalar(
            update(SessionDB)
            .where(SessionDB.id == session_id, SessionDB.user_id == user_id, SessionDB.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(SessionDB.id)
        )
        return revoked is not None

    async def revoke_all_but(self, user_id: UUID, keep: UUID, now: datetime) -> list[UUID]:
        revoked = await self._session.scalars(
            update(SessionDB)
            .where(SessionDB.user_id == user_id, SessionDB.id != keep, *_active_session(now))
            .values(revoked_at=now)
            .returning(SessionDB.id)
        )
        return list(revoked)

    async def reauthenticate(self, session_id: UUID, now: datetime) -> None:
        await self._session.execute(update(SessionDB).where(SessionDB.id == session_id).values(authenticated_at=now))


class PostgresPasskeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, passkey: Passkey) -> None:
        self._session.add(
            PasskeyDB(
                id=passkey.id,
                user_id=passkey.user_id,
                credential_id=passkey.credential_id,
                public_key=passkey.public_key,
                sign_count=passkey.sign_count,
                name=passkey.name,
                transports=passkey.transports,
                created_at=passkey.created_at,
                last_used_at=passkey.last_used_at,
            )
        )

    async def for_user(self, user_id: UUID) -> list[Passkey]:
        rows = await self._session.scalars(
            select(PasskeyDB).where(PasskeyDB.user_id == user_id).order_by(PasskeyDB.created_at, PasskeyDB.id)
        )
        return [_passkey(row) for row in rows]

    async def get(self, user_id: UUID, passkey_id: UUID) -> Passkey | None:
        row = await self._session.scalar(
            select(PasskeyDB).where(PasskeyDB.id == passkey_id, PasskeyDB.user_id == user_id)
        )
        return None if row is None else _passkey(row)

    async def by_credential_id(self, credential_id: bytes) -> tuple[Passkey, User] | None:
        row = (
            await self._session.execute(
                select(PasskeyDB, UserDB)
                .join(UserDB, UserDB.id == PasskeyDB.user_id)
                .where(PasskeyDB.credential_id == credential_id)
            )
        ).one_or_none()
        return None if row is None else (_passkey(row[0]), _user(row[1]))

    async def rename(self, passkey_id: UUID, name: str) -> None:
        await self._session.execute(update(PasskeyDB).where(PasskeyDB.id == passkey_id).values(name=name))

    async def record_use(self, passkey_id: UUID, seen_sign_count: int, sign_count: int, now: datetime) -> bool:
        updated = await self._session.scalar(
            update(PasskeyDB)
            .where(PasskeyDB.id == passkey_id, PasskeyDB.sign_count == seen_sign_count)
            .values(sign_count=sign_count, last_used_at=now)
            .returning(PasskeyDB.id)
        )
        return updated is not None

    async def remove(self, user_id: UUID, passkey_id: UUID) -> bool:
        removed = await self._session.scalar(
            delete(PasskeyDB).where(PasskeyDB.id == passkey_id, PasskeyDB.user_id == user_id).returning(PasskeyDB.id)
        )
        return removed is not None


class PostgresChallengeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, challenge: Challenge) -> None:
        self._session.add(
            PasskeyChallengeDB(
                id=challenge.id,
                ceremony=challenge.ceremony.value,
                challenge=challenge.value,
                session_id=challenge.session_id,
                expires_at=challenge.expires_at,
            )
        )

    async def take(
        self, challenge_id: UUID, ceremony: Ceremony, session_id: UUID | None, now: datetime
    ) -> Challenge | None:
        row = (
            await self._session.execute(
                delete(PasskeyChallengeDB)
                .where(
                    PasskeyChallengeDB.id == challenge_id,
                    PasskeyChallengeDB.ceremony == ceremony.value,
                    PasskeyChallengeDB.session_id.is_(None)
                    if session_id is None
                    else PasskeyChallengeDB.session_id == session_id,
                    PasskeyChallengeDB.expires_at > now,
                )
                .returning(PasskeyChallengeDB.challenge, PasskeyChallengeDB.expires_at)
            )
        ).one_or_none()
        if row is None:
            return None
        return Challenge(
            id=challenge_id, ceremony=ceremony, value=row.challenge, session_id=session_id, expires_at=row.expires_at
        )

    async def forget_expired(self, now: datetime) -> None:
        await self._session.execute(delete(PasskeyChallengeDB).where(PasskeyChallengeDB.expires_at <= now))


class PostgresSetupTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(self) -> None:
        await self._session.execute(select(func.pg_advisory_xact_lock(SETUP_LOCK_KEY)))

    async def replace(self, token_hash: bytes, now: datetime) -> None:
        await self._session.execute(delete(SetupTokenDB))
        self._session.add(SetupTokenDB(token_hash=token_hash, created_at=now))

    async def current(self) -> bytes | None:
        return await self._session.scalar(select(SetupTokenDB.token_hash))

    async def clear(self) -> None:
        await self._session.execute(delete(SetupTokenDB))


class PostgresFailureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(self, keys: Sequence[str]) -> None:
        # Always in the same order, so two transactions never wait for each other in a circle.
        for key in sorted(keys):
            await self._session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))

    async def get(self, keys: Sequence[str]) -> list[Failures]:
        rows = await self._session.scalars(select(SignInFailureDB).where(SignInFailureDB.key.in_(list(keys))))
        return [Failures(count=row.count, last_at=row.last_at) for row in rows]

    async def record(self, keys: Sequence[str], now: datetime, forget_before: datetime) -> None:
        if not keys:
            return
        statement = insert(SignInFailureDB).values([{"key": key, "count": 1, "last_at": now} for key in keys])
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[SignInFailureDB.key],
                set_={
                    "count": case((SignInFailureDB.last_at < forget_before, 1), else_=SignInFailureDB.count + 1),
                    "last_at": now,
                },
            )
        )

    async def uncount(self, keys: Sequence[str]) -> None:
        if keys:
            await self._session.execute(
                update(SignInFailureDB)
                .where(SignInFailureDB.key.in_(list(keys)))
                .values(count=func.greatest(SignInFailureDB.count - 1, 0))
            )

    async def clear(self, key: str) -> None:
        await self._session.execute(delete(SignInFailureDB).where(SignInFailureDB.key == key))

    async def forget_older_than(self, cutoff: datetime) -> None:
        await self._session.execute(delete(SignInFailureDB).where(SignInFailureDB.last_at < cutoff))


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


def _active_session(now: datetime) -> tuple[ColumnElement[bool], ...]:
    # Session.is_active, in SQL.
    return (
        SessionDB.revoked_at.is_(None),
        SessionDB.last_seen_at > now - IDLE_TIMEOUT,
        SessionDB.created_at > now - ABSOLUTE_LIFETIME,
    )


def _user_fields(user: User) -> dict[str, object]:
    return {
        "display_name": user.display_name,
        "locale": user.locale,
        "username": user.username,
        "email": user.email,
        "install_admin": user.install_admin,
        "disabled_at": user.disabled_at,
    }


def _user(row: UserDB) -> User:
    return User(
        id=row.id,
        display_name=row.display_name,
        locale=row.locale,
        username=row.username,
        email=row.email,
        install_admin=row.install_admin,
        disabled_at=row.disabled_at,
    )


def _session(row: SessionDB) -> Session:
    return Session(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        authenticated_at=row.authenticated_at,
        client=Client(user_agent=row.user_agent, ip=None if row.ip is None else str(row.ip)),
        revoked_at=row.revoked_at,
    )


def _passkey(row: PasskeyDB) -> Passkey:
    return Passkey(
        id=row.id,
        user_id=row.user_id,
        credential_id=row.credential_id,
        public_key=row.public_key,
        sign_count=row.sign_count,
        name=row.name,
        transports=list(row.transports),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


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

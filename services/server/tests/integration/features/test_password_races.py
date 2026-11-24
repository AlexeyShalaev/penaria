"""A password that changes while another attempt checks the old one: the old one wins nothing."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select, update
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.features.support.identity.domain.passwords import PasswordHasher
from penaria.features.support.identity.domain.secrets import SecretBox
from penaria.features.support.identity.domain.sessions import Client, CurrentSession
from penaria.features.support.identity.infra.orm import SessionDB
from penaria.features.support.identity.use_cases.account import ChangePassword, WrongPasswordError
from penaria.features.support.identity.use_cases.postman import Postman
from penaria.features.support.identity.use_cases.reauthentication import ReauthenticateWithPassword
from penaria.features.support.identity.use_cases.sessions import InvalidCredentialsError, SignIn
from penaria.integrations.postgres.transaction import PenariaTransaction
from tests.integration.conftest import OWNER

pytestmark = pytest.mark.integration

CLIENT = Client(user_agent="Test", ip="192.0.2.1")
MEANWHILE = "set by the owner meanwhile"
NEW = "a brand new secret"


class ChangingMidway:
    """Checks a password as the real hasher does, while the owner sets another one in the meantime."""

    def __init__(self, real: PasswordHasher, uow: AsyncSQLAlchemyUnitOfWork[PenariaTransaction]) -> None:
        self._real = real
        self._uow = uow

    async def hash(self, password: str) -> str:
        return await self._real.hash(password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        matches = await self._real.verify(password_hash, password)
        new_hash = await self._real.hash(MEANWHILE)
        async with self._uow.transaction() as tx:
            user = await tx.users.by_username(OWNER["username"])
            assert user is not None
            await tx.passwords.set(user.id, new_hash, datetime.now(UTC))
        return matches

    def needs_rehash(self, password_hash: str) -> bool:
        # Asked to redo the hash, so a stale write would put the old password back.
        return True


async def test_a_sign_in_with_a_password_changed_meanwhile_opens_no_session(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    uow = await container.container.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])
    hasher = ChangingMidway(await container.container.get(PasswordHasher), uow)

    with pytest.raises(InvalidCredentialsError):
        await SignIn(uow, hasher).execute(username=OWNER["username"], password=OWNER["password"], client=CLIENT)

    assert len((await api.get("/me/sessions")).json()) == 1
    assert (await api.post("/sign-in", json={"username": "owner", "password": OWNER["password"]})).status_code == 401


async def test_a_change_checked_against_a_password_changed_meanwhile_is_refused(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    uow = await container.container.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])
    hasher = ChangingMidway(await container.container.get(PasswordHasher), uow)
    [session] = (await api.get("/me/sessions")).json()
    current = CurrentSession(
        id=UUID(session["id"]), user_id=UUID((await api.get("/me")).json()["id"]), authenticated_at=datetime.now(UTC)
    )

    with pytest.raises(WrongPasswordError):
        postman = await container.container.get(Postman)
        await ChangePassword(uow, hasher, postman).execute(
            current, current_password=OWNER["password"], new_password=NEW
        )

    signed_in = await api.post("/sign-in", json={"username": "owner", "password": MEANWHILE})
    assert signed_in.status_code == 200


async def test_a_confirmation_checked_against_a_password_changed_meanwhile_is_refused(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    uow = await container.container.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])
    hasher = ChangingMidway(await container.container.get(PasswordHasher), uow)
    long_ago = datetime.now(UTC) - timedelta(minutes=11)
    async with uow.transaction() as tx:
        await tx.session.execute(update(SessionDB).values(authenticated_at=long_ago))
    [session] = (await api.get("/me/sessions")).json()
    current = CurrentSession(
        id=UUID(session["id"]), user_id=UUID((await api.get("/me")).json()["id"]), authenticated_at=long_ago
    )

    box = await container.container.get(SecretBox)
    postman = await container.container.get(Postman)

    with pytest.raises(WrongPasswordError):
        await ReauthenticateWithPassword(uow, hasher, box, postman).execute(current, OWNER["password"], None)

    async with uow.query() as tx:
        assert await tx.session.scalar(select(SessionDB.authenticated_at)) == long_ago

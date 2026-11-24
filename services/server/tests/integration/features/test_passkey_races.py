"""A passkey that changes while its answer is checked: the answer opens no session and confirms nothing."""

import asyncio
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import TextClause, func, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.passkeys import (
    Assertion,
    Challenge,
    CredentialJson,
    InvalidPasskeyError,
    NewCredential,
    Passkey,
    PasskeyRejectedError,
    RelyingParty,
)
from penaria.features.support.identity.domain.sessions import Client, CurrentSession
from penaria.features.support.identity.infra.orm import SessionDB
from penaria.features.support.identity.use_cases.reauthentication import (
    ReauthenticateWithPasskey,
    StartPasskeyReauthentication,
)
from penaria.features.support.identity.use_cases.sessions import SignInWithPasskey, StartPasskeySignIn
from tests.authenticator import Authenticator
from tests.integration.conftest import PUBLIC_URL
from tests.integration.helpers import add_passkey, uow_of

pytestmark = pytest.mark.integration

CLIENT = Client(user_agent="Test", ip="192.0.2.1")
USED_BY_ANOTHER_SIGN_IN = text("UPDATE identity_passkeys SET sign_count = sign_count + 1")
REMOVED = text("DELETE FROM identity_passkeys")


class ChangingMidway:
    """Checks answers as the real relying party does, while the passkey changes in the meantime.

    The check is synchronous, so the change runs to its commit on a connection of its own.
    """

    def __init__(self, real: RelyingParty, database_url: str, change: TextClause) -> None:
        self._real = real
        self._database_url = database_url
        self._change = change

    def registration_options(self, user: User, challenge: Challenge, existing: Sequence[Passkey]) -> dict[str, Any]:
        return self._real.registration_options(user, challenge, existing)

    def verify_registration(self, credential: CredentialJson, challenge: Challenge) -> NewCredential:
        return self._real.verify_registration(credential, challenge)

    def authentication_options(self, challenge: Challenge, allowed: Sequence[Passkey]) -> dict[str, Any]:
        return self._real.authentication_options(challenge, allowed)

    def read_assertion(self, credential: CredentialJson) -> Assertion:
        return self._real.read_assertion(credential)

    def verify_authentication(self, credential: CredentialJson, challenge: Challenge, passkey: Passkey) -> int:
        sign_count = self._real.verify_authentication(credential, challenge, passkey)
        worker = threading.Thread(target=asyncio.run, args=(self._commit_change(),))
        worker.start()
        worker.join()
        return sign_count

    async def _commit_change(self) -> None:
        engine = create_async_engine(self._database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.execute(self._change)
        finally:
            await engine.dispose()


@pytest.fixture
async def phone(api: httpx.AsyncClient) -> Authenticator:
    device = Authenticator(PUBLIC_URL, counting=True)
    assert (await add_passkey(api, device)).status_code == 201
    return device


@pytest.fixture
async def real(container: DishkaContainer) -> RelyingParty:
    relying_party: RelyingParty = await container.container.get(RelyingParty)
    return relying_party


@pytest.mark.parametrize("change", [USED_BY_ANOTHER_SIGN_IN, REMOVED], ids=["used meanwhile", "removed meanwhile"])
async def test_a_passkey_changed_while_its_answer_is_checked_opens_no_session(
    phone: Authenticator, container: DishkaContainer, real: RelyingParty, test_database_url: str, change: TextClause
) -> None:
    uow = await uow_of(container)
    ceremony = await StartPasskeySignIn(uow, real).execute(CLIENT)
    sign_in = SignInWithPasskey(uow, ChangingMidway(real, test_database_url, change))

    with pytest.raises(InvalidPasskeyError):
        await sign_in.execute(challenge_id=ceremony.challenge_id, credential=phone.get(ceremony.options), client=CLIENT)

    async with uow.query() as tx:
        assert await tx.session.scalar(select(func.count()).select_from(SessionDB)) == 1


async def test_a_passkey_used_while_its_answer_is_checked_confirms_nothing(
    api: httpx.AsyncClient, phone: Authenticator, container: DishkaContainer, real: RelyingParty, test_database_url: str
) -> None:
    uow = await uow_of(container)
    long_ago = datetime.now(UTC) - timedelta(minutes=11)
    async with uow.transaction() as tx:
        await tx.session.execute(update(SessionDB).values(authenticated_at=long_ago))
        session_id, user_id = (await tx.session.execute(select(SessionDB.id, SessionDB.user_id))).one()
    assert user_id is not None
    current = CurrentSession(id=session_id, user_id=user_id, authenticated_at=long_ago)
    ceremony = await StartPasskeyReauthentication(uow, real).execute(current)
    confirm = ReauthenticateWithPasskey(uow, ChangingMidway(real, test_database_url, USED_BY_ANOTHER_SIGN_IN))

    with pytest.raises(PasskeyRejectedError):
        await confirm.execute(current, challenge_id=ceremony.challenge_id, credential=phone.get(ceremony.options))

    assert (await api.post("/me/passkeys/options")).json()["code"] == "recent_sign_in_required"

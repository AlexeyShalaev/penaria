"""Passkeys through the HTTP API, as the web app uses them, with a software authenticator for the browser."""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import delete, select, update
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.infra.orm import PasskeyChallengeDB, PasskeyDB, PasswordDB, SessionDB, UserDB
from penaria.features.support.platform.infra.orm import JournalEventDB
from penaria.integrations.postgres.transaction import PenariaTransaction
from tests.authenticator import Authenticator
from tests.integration.conftest import OWNER, PUBLIC_URL

pytestmark = pytest.mark.integration

NewClient = Callable[..., httpx.AsyncClient]
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
WRONG = "not the password"
RP_ID = "test"


@pytest.fixture
def phone() -> Authenticator:
    return Authenticator(PUBLIC_URL)


async def uow_of(container: DishkaContainer) -> AsyncSQLAlchemyUnitOfWork[PenariaTransaction]:
    return await container.container.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])


async def add_passkey(client: httpx.AsyncClient, device: Authenticator, name: str = "Phone") -> httpx.Response:
    started = await client.post("/me/passkeys/options")
    assert started.status_code == 200, started.text
    ceremony = started.json()
    credential = device.create(ceremony["options"])
    return await client.post(
        "/me/passkeys", json={"challenge_id": ceremony["challenge_id"], "credential": credential, "name": name}
    )


async def sign_in_with(client: httpx.AsyncClient, device: Authenticator) -> httpx.Response:
    ceremony = (await client.post("/sign-in/passkey/options")).json()
    return await client.post(
        "/sign-in/passkey",
        json={"challenge_id": ceremony["challenge_id"], "credential": device.get(ceremony["options"])},
    )


async def reauthenticate_with(client: httpx.AsyncClient, device: Authenticator) -> httpx.Response:
    ceremony = (await client.post("/me/reauthenticate/passkey/options")).json()
    return await client.post(
        "/me/reauthenticate/passkey",
        json={"challenge_id": ceremony["challenge_id"], "credential": device.get(ceremony["options"])},
    )


async def age_sign_ins(container: DishkaContainer, minutes: int = 11) -> None:
    """Every session's person proved who they are ``minutes`` ago."""
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(
            update(SessionDB).values(authenticated_at=datetime.now(UTC) - timedelta(minutes=minutes))
        )


@pytest.fixture
async def with_passkey(api: httpx.AsyncClient, phone: Authenticator) -> dict[str, Any]:
    """The owner, signed in as ``api``, has added ``phone``'s passkey; its listing."""
    response = await add_passkey(api, phone)
    assert response.status_code == 201, response.text
    return dict(response.json())


# Adding passkeys


async def test_a_passkey_is_added_and_listed(api: httpx.AsyncClient, phone: Authenticator) -> None:
    response = await add_passkey(api, phone, name=" Safari on iPhone ")

    assert response.status_code == 201, response.text
    added = response.json()
    assert added.keys() == {"id", "name", "created_at", "last_used_at"}
    assert UUID_PATTERN.match(added["id"])
    assert (added["name"], added["last_used_at"]) == ("Safari on iPhone", None)
    assert (await api.get("/me/passkeys")).json() == [added]


async def test_the_options_carry_the_account_and_exclude_its_passkeys(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], phone: Authenticator
) -> None:
    response = await api.post("/me/passkeys/options")

    options = response.json()["options"]
    assert options["rp"] == {"id": RP_ID, "name": "Penaria"}
    assert (options["user"]["name"], options["user"]["displayName"]) == ("owner", "Owner")
    assert [c["id"] for c in options["excludeCredentials"]] == [phone.create(options)["id"]]


async def test_the_same_passkey_cannot_be_added_twice(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], phone: Authenticator
) -> None:
    response = await add_passkey(api, phone)

    assert response.status_code == 409
    assert response.json()["code"] == "passkey_already_registered"


async def test_adding_a_passkey_needs_a_recent_sign_in(
    api: httpx.AsyncClient, phone: Authenticator, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await api.post("/me/passkeys/options")

    assert response.status_code == 403
    assert response.json()["code"] == "recent_sign_in_required"
    assert response.json()["params"] == {"max_age_seconds": 600}


async def test_a_sign_in_that_ages_during_the_ceremony_adds_nothing(
    api: httpx.AsyncClient, phone: Authenticator, container: DishkaContainer
) -> None:
    ceremony = (await api.post("/me/passkeys/options")).json()
    await age_sign_ins(container)

    response = await api.post(
        "/me/passkeys",
        json={"challenge_id": ceremony["challenge_id"], "credential": phone.create(ceremony["options"]), "name": "P"},
    )

    assert response.json()["code"] == "recent_sign_in_required"
    assert (await api.get("/me/passkeys")).json() == []


async def test_a_challenge_adds_one_passkey_at_most(api: httpx.AsyncClient, phone: Authenticator) -> None:
    ceremony = (await api.post("/me/passkeys/options")).json()
    body = {"challenge_id": ceremony["challenge_id"], "credential": phone.create(ceremony["options"]), "name": "P"}

    first = await api.post("/me/passkeys", json=body)
    second = await api.post(
        "/me/passkeys", json={**body, "credential": Authenticator(PUBLIC_URL).create(ceremony["options"])}
    )

    assert first.status_code == 201
    assert second.status_code == 400
    assert second.json()["code"] == "passkey_rejected"


async def test_a_challenge_of_another_session_adds_nothing(
    api: httpx.AsyncClient, new_client: NewClient, phone: Authenticator
) -> None:
    laptop = new_client()
    assert (await laptop.post("/sign-in", json={"username": "owner", "password": OWNER["password"]})).status_code == 200
    ceremony = (await api.post("/me/passkeys/options")).json()

    response = await laptop.post(
        "/me/passkeys",
        json={"challenge_id": ceremony["challenge_id"], "credential": phone.create(ceremony["options"]), "name": "P"},
    )

    assert response.json()["code"] == "passkey_rejected"


async def test_an_expired_challenge_adds_nothing(
    api: httpx.AsyncClient, phone: Authenticator, container: DishkaContainer
) -> None:
    ceremony = (await api.post("/me/passkeys/options")).json()
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(PasskeyChallengeDB).values(expires_at=datetime.now(UTC)))

    response = await api.post(
        "/me/passkeys",
        json={"challenge_id": ceremony["challenge_id"], "credential": phone.create(ceremony["options"]), "name": "P"},
    )

    assert response.json()["code"] == "passkey_rejected"


async def test_a_passkey_made_on_another_site_is_rejected(api: httpx.AsyncClient) -> None:
    response = await add_passkey(api, Authenticator("https://evil.example"))

    assert response.status_code == 400
    assert response.json()["code"] == "passkey_rejected"


async def test_a_passkey_needs_a_name(api: httpx.AsyncClient, phone: Authenticator) -> None:
    response = await add_passkey(api, phone, name="   ")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_passkey_name"


async def test_expired_challenges_are_forgotten(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    await api.post("/sign-in/passkey/options")
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(PasskeyChallengeDB).values(expires_at=datetime.now(UTC)))

    await api.post("/sign-in/passkey/options")

    async with (await uow_of(container)).query() as tx:
        assert len((await tx.session.scalars(select(PasskeyChallengeDB.id))).all()) == 1


# Signing in with a passkey


async def test_a_passkey_signs_in_without_a_username(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient
) -> None:
    laptop = new_client()

    response = await sign_in_with(laptop, phone)

    assert response.status_code == 200, response.text
    assert response.json()["username"] == "owner"
    assert response.headers["set-cookie"].startswith("penaria_session=")
    assert (await laptop.get("/me")).status_code == 200
    [listed] = (await laptop.get("/me/passkeys")).json()
    assert listed["last_used_at"] is not None


async def test_signing_in_offers_every_passkey(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/sign-in/passkey/options")

    assert response.status_code == 200
    options = response.json()["options"]
    assert (options["rpId"], options["allowCredentials"], options["userVerification"]) == (RP_ID, [], "required")


async def test_a_sign_in_challenge_is_used_once(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient
) -> None:
    client = new_client()
    ceremony = (await client.post("/sign-in/passkey/options")).json()
    body = {"challenge_id": ceremony["challenge_id"], "credential": phone.get(ceremony["options"])}

    first = await client.post("/sign-in/passkey", json=body)
    replayed = await new_client().post("/sign-in/passkey", json=body)

    assert first.status_code == 200
    assert replayed.status_code == 401
    assert replayed.json()["code"] == "invalid_passkey"


async def test_an_unknown_passkey_and_a_wrong_signature_answer_the_same(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient
) -> None:
    unknown = await sign_in_with(new_client(), Authenticator.stranger(PUBLIC_URL, RP_ID))
    forged = await sign_in_with(new_client(), phone.impostor())

    assert unknown.status_code == forged.status_code == 401
    assert unknown.json() == forged.json()
    assert unknown.json()["code"] == "invalid_passkey"


async def test_a_passkey_of_a_disabled_account_does_not_sign_in(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient, container: DishkaContainer
) -> None:
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(UserDB).values(disabled_at=datetime.now(UTC)))

    response = await sign_in_with(new_client(), phone)

    assert response.json()["code"] == "invalid_passkey"


async def test_a_cloned_authenticator_is_refused(api: httpx.AsyncClient, new_client: NewClient) -> None:
    key = Authenticator(PUBLIC_URL, counting=True)
    assert (await add_passkey(api, key)).status_code == 201
    clone = key.clone()
    assert (await sign_in_with(new_client(), key)).status_code == 200

    response = await sign_in_with(new_client(), clone)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_passkey"


async def test_a_removed_passkey_no_longer_signs_in(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient
) -> None:
    assert (await api.delete(f"/me/passkeys/{with_passkey['id']}")).status_code == 204

    assert (await sign_in_with(new_client(), phone)).json()["code"] == "invalid_passkey"


async def test_failed_passkey_sign_ins_are_limited_per_address(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient, app: FastAPI
) -> None:
    def from_address(ip: str) -> httpx.AsyncClient:
        return new_client(transport=httpx.ASGITransport(app=app, client=(ip, 1)))

    guesser = from_address("192.0.2.1")
    stranger = Authenticator.stranger(PUBLIC_URL, RP_ID)
    statuses = [(await sign_in_with(guesser, stranger)).status_code for _ in range(5)]

    blocked = await sign_in_with(guesser, phone)

    assert statuses == [401] * 5
    assert blocked.status_code == 429
    assert (await sign_in_with(from_address("198.51.100.1"), phone)).status_code == 200


async def test_a_passkey_signs_in_while_the_password_is_blocked(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient, app: FastAPI
) -> None:
    for octet in range(1, 6):
        attacker = new_client(transport=httpx.ASGITransport(app=app, client=(f"192.0.2.{octet}", 1)))
        await attacker.post("/sign-in", json={"username": "owner", "password": WRONG})
    owner = new_client(transport=httpx.ASGITransport(app=app, client=("198.51.100.1", 1)))
    assert (await owner.post("/sign-in", json={"username": "owner", "password": OWNER["password"]})).status_code == 429

    assert (await sign_in_with(owner, phone)).status_code == 200


async def test_signing_in_with_a_passkey_from_another_site_is_refused(
    with_passkey: dict[str, Any], phone: Authenticator, new_client: NewClient
) -> None:
    client = new_client(headers={"origin": "https://evil.example"})

    response = await client.post("/sign-in/passkey/options")

    assert response.json()["code"] == "cross_origin_request"


# Confirming it is you


async def test_the_password_makes_the_sign_in_recent_again(
    api: httpx.AsyncClient, phone: Authenticator, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await api.post("/me/reauthenticate", json={"password": OWNER["password"]})

    assert response.status_code == 204
    assert (await add_passkey(api, phone)).status_code == 201


async def test_a_passkey_makes_the_sign_in_recent_again(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], phone: Authenticator, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await reauthenticate_with(api, phone)

    assert response.status_code == 204
    assert (await api.delete(f"/me/passkeys/{with_passkey['id']}")).status_code == 204


async def test_a_wrong_password_does_not_confirm(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    await age_sign_ins(container)

    response = await api.post("/me/reauthenticate", json={"password": WRONG})

    assert response.status_code == 400
    assert response.json()["code"] == "wrong_password"
    assert (await api.post("/me/passkeys/options")).json()["code"] == "recent_sign_in_required"


async def test_wrong_passwords_to_confirm_are_limited(api: httpx.AsyncClient) -> None:
    statuses = [(await api.post("/me/reauthenticate", json={"password": WRONG})).status_code for _ in range(5)]

    blocked = await api.post("/me/reauthenticate", json={"password": OWNER["password"]})

    assert statuses == [400] * 5
    assert blocked.status_code == 429


async def test_only_the_account_s_own_passkey_confirms(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    neighbour_key = Authenticator(PUBLIC_URL)
    assert (await add_passkey(api, Authenticator(PUBLIC_URL))).status_code == 201
    assert (await add_passkey(api, neighbour_key)).status_code == 201
    async with (await uow_of(container)).transaction() as tx:
        neighbour = await _neighbour(tx)
        await tx.session.execute(
            update(PasskeyDB).where(PasskeyDB.credential_id == neighbour_key.credential_id).values(user_id=neighbour)
        )
    ceremony = (await api.post("/me/reauthenticate/passkey/options")).json()
    options = {**ceremony["options"], "allowCredentials": []}

    response = await api.post(
        "/me/reauthenticate/passkey",
        json={"challenge_id": ceremony["challenge_id"], "credential": neighbour_key.get(options)},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "passkey_rejected"


async def test_confirming_with_a_passkey_needs_one(api: httpx.AsyncClient) -> None:
    response = await api.post("/me/reauthenticate/passkey/options")

    assert response.status_code == 404
    assert response.json()["code"] == "passkey_not_found"


# Naming and removing passkeys


async def test_a_passkey_can_be_renamed(api: httpx.AsyncClient, with_passkey: dict[str, Any]) -> None:
    response = await api.patch(f"/me/passkeys/{with_passkey['id']}", json={"name": "Work laptop"})

    assert response.json() == {**with_passkey, "name": "Work laptop"}
    assert (await api.get("/me/passkeys")).json() == [{**with_passkey, "name": "Work laptop"}]


async def test_renaming_needs_no_recent_sign_in(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await api.patch(f"/me/passkeys/{with_passkey['id']}", json={"name": "Work laptop"})

    assert response.status_code == 200


async def test_removing_a_passkey_needs_a_recent_sign_in(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await api.delete(f"/me/passkeys/{with_passkey['id']}")

    assert response.json()["code"] == "recent_sign_in_required"
    assert len((await api.get("/me/passkeys")).json()) == 1


async def test_the_last_way_to_sign_in_cannot_be_removed(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], container: DishkaContainer
) -> None:
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(delete(PasswordDB))

    response = await api.delete(f"/me/passkeys/{with_passkey['id']}")

    assert response.status_code == 409
    assert response.json()["code"] == "last_sign_in_method"


async def test_a_passkey_of_another_account_is_not_found(
    api: httpx.AsyncClient, with_passkey: dict[str, Any], container: DishkaContainer
) -> None:
    async with (await uow_of(container)).transaction() as tx:
        neighbour = await _neighbour(tx)
        await tx.session.execute(update(PasskeyDB).values(user_id=neighbour))

    renamed = await api.patch(f"/me/passkeys/{with_passkey['id']}", json={"name": "Mine now"})
    removed = await api.delete(f"/me/passkeys/{with_passkey['id']}")

    assert renamed.status_code == removed.status_code == 404
    assert renamed.json()["code"] == removed.json()["code"] == "passkey_not_found"
    assert (await api.get("/me/passkeys")).json() == []


# The journal


async def test_passkey_events_are_journalled(
    api: httpx.AsyncClient, phone: Authenticator, new_client: NewClient, container: DishkaContainer
) -> None:
    passkey_id = (await add_passkey(api, phone)).json()["id"]
    await api.patch(f"/me/passkeys/{passkey_id}", json={"name": "Phone 2"})
    await sign_in_with(new_client(), phone)
    await sign_in_with(new_client(), phone.impostor())
    await reauthenticate_with(api, phone)
    await api.post("/me/reauthenticate", json={"password": OWNER["password"]})
    await api.delete(f"/me/passkeys/{passkey_id}")

    async with (await uow_of(container)).query() as tx:
        rows = (
            await tx.session.execute(
                select(JournalEventDB.type, JournalEventDB.actor, JournalEventDB.payload)
                .where(JournalEventDB.type != "account.setup_completed")
                .order_by(JournalEventDB.seq)
            )
        ).all()

    passkey = {"user_id": "uuid", "passkey_id": passkey_id}
    session = {"user_id": "uuid", "session_id": "uuid"}
    assert [(row.type, row.actor["kind"], _shape(row.payload)) for row in rows] == [
        ("account.signed_in", "user", {**session, "ip": "127.0.0.1"}),
        ("account.passkey_added", "user", {**passkey, "name": "Phone"}),
        ("account.passkey_renamed", "user", {**passkey, "name": "Phone 2"}),
        ("account.signed_in", "user", {**session, "ip": "127.0.0.1", "passkey_id": passkey_id}),
        ("account.sign_in_failed", "system", {**passkey, "ip": "127.0.0.1"}),
        ("account.reauthenticated", "user", {**session, "passkey_id": passkey_id}),
        ("account.reauthenticated", "user", session),
        ("account.passkey_removed", "user", passkey),
    ]


async def _neighbour(tx: PenariaTransaction) -> UUID:
    neighbour = User(display_name="Neighbour", locale="en", username="neighbour")
    await tx.users.add(neighbour)
    return neighbour.id


def _shape(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with the ids of users and sessions replaced by "uuid", so it compares whole."""
    return {
        key: "uuid" if key in ("user_id", "session_id") and UUID_PATTERN.match(value) else value
        for key, value in payload.items()
    }

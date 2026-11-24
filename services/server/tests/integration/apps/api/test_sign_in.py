"""Setup, sign-in, sessions and the account through the HTTP API, as the web app uses them."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher as Argon2Hasher
from fastapi import FastAPI
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select, update

from penaria.features.shared.actor import Actor
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.domain.sessions import Client, Session
from penaria.features.support.identity.infra.orm import PasswordDB, SessionDB, SignInFailureDB
from penaria.features.support.identity.use_cases.homes import CreateHome
from penaria.features.support.identity.use_cases.setup import IssueSetupToken
from penaria.features.support.platform.infra.orm import JournalEventDB
from tests.integration.conftest import OWNER, PUBLIC_URL
from tests.integration.helpers import UUID_PATTERN, WRONG, NewClient, from_address, shape, uow_of

pytestmark = pytest.mark.integration

NEW = "a brand new secret"
ACCOUNT = {
    "id": str,
    "username": "owner",
    "display_name": "Owner",
    "email": None,
    "locale": "en",
    "install_admin": True,
}


def account(**changes: Any) -> dict[str, Any]:
    return {**ACCOUNT, **changes}


def matches(data: dict[str, Any], expected: dict[str, Any]) -> bool:
    return data.keys() == expected.keys() and all(
        isinstance(data[key], value) if isinstance(value, type) else data[key] == value
        for key, value in expected.items()
    )


async def sign_in(client: httpx.AsyncClient, password: str = OWNER["password"], **kwargs: Any) -> httpx.Response:
    return await client.post("/sign-in", json={"username": OWNER["username"], "password": password}, **kwargs)


async def fail_to_sign_in(client: httpx.AsyncClient, times: int, username: str = OWNER["username"]) -> list[int]:
    statuses = []
    for _ in range(times):
        response = await client.post("/sign-in", json={"username": username, "password": WRONG})
        statuses.append(response.status_code)
    return statuses


# Setup


async def test_a_fresh_install_needs_setup(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.get("/setup")

    assert response.json() == {"needed": True}


async def test_setup_makes_the_owner_account_and_signs_in(anonymous: httpx.AsyncClient, setup_token: str) -> None:
    response = await anonymous.post("/setup", json={**OWNER, "username": " Owner ", "token": setup_token})

    assert response.status_code == 200, response.text
    assert matches(response.json(), ACCOUNT)
    assert matches((await anonymous.get("/me")).json(), ACCOUNT)
    assert (await anonymous.get("/setup")).json() == {"needed": False}


async def test_setup_with_a_wrong_token_is_refused(anonymous: httpx.AsyncClient, setup_token: str) -> None:
    response = await anonymous.post("/setup", json={**OWNER, "token": "0" * 32})

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_setup_token"
    assert (await anonymous.get("/setup")).json() == {"needed": True}


async def test_a_second_setup_is_refused(api: httpx.AsyncClient, anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/setup", json={**OWNER, "username": "intruder", "token": "0" * 32})

    assert response.status_code == 409
    assert response.json()["code"] == "already_set_up"


async def test_a_restart_before_setup_invalidates_the_old_token(
    anonymous: httpx.AsyncClient, setup_token: str, container: DishkaContainer
) -> None:
    new_token = await (await container.container.get(IssueSetupToken)).execute()

    refused = await anonymous.post("/setup", json={**OWNER, "token": setup_token})
    accepted = await anonymous.post("/setup", json={**OWNER, "token": new_token})

    assert refused.status_code == 403
    assert accepted.status_code == 200


async def test_no_token_is_issued_once_set_up(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    assert await (await container.container.get(IssueSetupToken)).execute() is None


async def test_setup_refuses_a_weak_password(anonymous: httpx.AsyncClient, setup_token: str) -> None:
    response = await anonymous.post("/setup", json={**OWNER, "password": "password1234", "token": setup_token})

    assert response.status_code == 400
    assert response.json()["code"] == "weak_password"
    assert response.json()["params"]["reason"] == "common"


async def test_setup_keeps_the_homes_of_the_local_user_from_before_sign_in(
    anonymous: httpx.AsyncClient, setup_token: str, container: DishkaContainer
) -> None:
    local_user = User(display_name="Owner", locale="en")
    async with (await uow_of(container)).transaction() as tx:
        await tx.users.add(local_user)
    await (await container.container.get(CreateHome)).execute(
        Actor.user(local_user.id), name="Country house", timezone="Europe/Moscow", locale="ru"
    )

    response = await anonymous.post("/setup", json={**OWNER, "display_name": "Alex", "token": setup_token})

    assert matches(response.json(), account(id=str(local_user.id), display_name="Alex"))
    assert [home["name"] for home in (await anonymous.get("/homes")).json()] == ["Country house"]


# Signing in and out


async def test_signing_in_opens_a_session(api: httpx.AsyncClient, new_client: NewClient) -> None:
    phone = new_client()

    response = await sign_in(phone)

    assert response.status_code == 200
    assert matches(response.json(), ACCOUNT)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("penaria_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie  # PENARIA_PUBLIC_URL of the tests is plain HTTP
    assert (await phone.get("/me")).status_code == 200


async def test_a_wrong_password_and_an_unknown_user_answer_the_same(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    wrong_password = await sign_in(new_client(), password=WRONG)
    unknown_user = await new_client().post("/sign-in", json={"username": "nobody", "password": OWNER["password"]})

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["code"] == "invalid_credentials"


async def test_signing_out_ends_the_session(api: httpx.AsyncClient) -> None:
    response = await api.post("/sign-out")

    assert response.status_code == 204
    assert 'penaria_session=""' in response.headers["set-cookie"]
    assert (await api.get("/me")).json()["code"] == "unauthenticated"


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/me"),
        ("GET", "/homes"),
        ("POST", "/homes"),
        ("GET", "/entities/0190c5a0-0000-7000-8000-000000000000"),
        ("GET", "/me/sessions"),
        ("POST", "/sign-out"),
    ],
)
async def test_without_a_session_the_api_answers_401(anonymous: httpx.AsyncClient, method: str, url: str) -> None:
    # No body: the missing session is reported before the invalid request.
    response = await anonymous.request(method, url)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "unauthenticated"


async def test_a_session_unused_for_thirty_days_has_ended(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(SessionDB).values(last_seen_at=datetime.now(UTC) - timedelta(days=30)))

    assert (await api.get("/me")).status_code == 401


async def test_five_failures_make_the_next_attempt_wait(api: httpx.AsyncClient, new_client: NewClient) -> None:
    attacker = new_client()
    for _ in range(5):
        assert (await sign_in(attacker, password=WRONG)).status_code == 401

    response = await sign_in(attacker)

    assert response.status_code == 429
    assert response.json()["code"] == "too_many_attempts"
    assert response.json()["params"]["retry_after_seconds"] in range(1, 31)


async def test_the_wait_applies_to_the_account_from_any_address(
    api: httpx.AsyncClient, new_client: NewClient, app: FastAPI
) -> None:
    def from_address(ip: str) -> httpx.AsyncClient:
        return new_client(transport=httpx.ASGITransport(app=app, client=(ip, 1)))

    for octet in range(1, 6):
        assert (await sign_in(from_address(f"192.0.2.{octet}"), password=WRONG)).status_code == 401

    assert (await sign_in(from_address("198.51.100.1"))).status_code == 429


# The account


async def test_the_account_can_be_renamed_and_switch_language(api: httpx.AsyncClient) -> None:
    response = await api.patch("/me", json={"display_name": "Alex", "locale": "ru"})

    assert matches(response.json(), account(display_name="Alex", locale="ru"))
    assert matches((await api.get("/me")).json(), account(display_name="Alex", locale="ru"))


async def test_the_sessions_list_marks_the_current_one(api: httpx.AsyncClient, new_client: NewClient) -> None:
    await sign_in(new_client(headers={"user-agent": "Phone"}))

    sessions = (await api.get("/me/sessions")).json()

    assert sorted((s["user_agent"], s["current"]) for s in sessions) == [
        ("Phone", False),
        (f"python-httpx/{httpx.__version__}", True),
    ]
    assert {s["ip"] for s in sessions} == {"127.0.0.1"}


async def test_a_session_can_be_ended_from_another(api: httpx.AsyncClient, new_client: NewClient) -> None:
    phone = new_client()
    await sign_in(phone)
    [phone_session] = [s for s in (await api.get("/me/sessions")).json() if not s["current"]]

    response = await api.delete(f"/me/sessions/{phone_session['id']}")

    assert response.status_code == 204
    assert (await phone.get("/me")).status_code == 401
    assert (await api.get("/me")).status_code == 200
    assert (await api.delete(f"/me/sessions/{phone_session['id']}")).json()["code"] == "session_not_found"


async def test_signing_out_everywhere_else_keeps_this_session(api: httpx.AsyncClient, new_client: NewClient) -> None:
    phone, laptop = new_client(), new_client()
    await sign_in(phone)
    await sign_in(laptop)

    response = await api.post("/me/sessions:revoke-others")

    assert response.json() == {"revoked": 2}
    assert [(await c.get("/me")).status_code for c in (phone, laptop, api)] == [401, 401, 200]


async def test_changing_the_password_needs_the_current_one(api: httpx.AsyncClient) -> None:
    response = await api.post("/me/password", json={"current_password": WRONG, "new_password": NEW})

    assert response.status_code == 400
    assert response.json()["code"] == "wrong_password"


async def test_a_new_password_signs_out_the_other_sessions(api: httpx.AsyncClient, new_client: NewClient) -> None:
    phone = new_client()
    await sign_in(phone)

    response = await api.post("/me/password", json={"current_password": OWNER["password"], "new_password": NEW})

    assert response.status_code == 204
    assert (await phone.get("/me")).status_code == 401
    assert (await api.get("/me")).status_code == 200
    assert (await sign_in(new_client())).status_code == 401
    assert (await sign_in(new_client(), password=NEW)).status_code == 200


# Requests from other sites


@pytest.mark.parametrize(
    "headers",
    [{"origin": "https://evil.example"}, {"referer": "https://evil.example/page"}, {"origin": "null"}],
)
async def test_a_change_asked_for_by_another_site_is_refused(api: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await api.post("/homes", json={"name": "Flat", "timezone": "UTC", "locale": "en"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "cross_origin_request"


async def test_signing_in_from_another_site_is_refused(api: httpx.AsyncClient, new_client: NewClient) -> None:
    response = await sign_in(new_client(), headers={"origin": "https://evil.example"})

    assert response.status_code == 403
    assert response.json()["code"] == "cross_origin_request"


async def test_the_install_s_own_pages_may_change_things(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/homes", json={"name": "Flat", "timezone": "UTC", "locale": "en"}, headers={"origin": PUBLIC_URL}
    )

    assert response.status_code == 201


async def test_a_malformed_referer_is_refused(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/homes", json={"name": "Flat", "timezone": "UTC", "locale": "en"}, headers={"referer": "https://test:99999/"}
    )

    assert response.status_code == 403


async def test_reading_from_another_site_is_not_refused(api: httpx.AsyncClient) -> None:
    assert (await api.get("/me", headers={"origin": "https://evil.example"})).status_code == 200


# More on sessions


async def test_a_forged_cookie_answers_401(new_client: NewClient, api: httpx.AsyncClient) -> None:
    response = await new_client(cookies={"penaria_session": "forged"}).get("/me")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_the_username_is_not_case_sensitive(api: httpx.AsyncClient, new_client: NewClient) -> None:
    response = await new_client().post("/sign-in", json={"username": " OWNER ", "password": OWNER["password"]})

    assert response.status_code == 200
    assert response.json()["username"] == "owner"


async def test_using_a_session_keeps_it_open(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    long_ago = datetime.now(UTC) - timedelta(days=29)
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(SessionDB).values(last_seen_at=long_ago))

    assert (await api.get("/me")).status_code == 200
    async with (await uow_of(container)).query() as tx:
        last_seen = await tx.session.scalar(select(SessionDB.last_seen_at))
    assert last_seen is not None
    assert datetime.now(UTC) - last_seen < timedelta(minutes=1)


async def test_ended_sessions_are_not_listed_or_ended_again(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    await sign_in(new_client(headers={"user-agent": "Old phone"}))
    await sign_in(new_client(headers={"user-agent": "Tablet"}))
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(
            update(SessionDB)
            .where(SessionDB.user_agent == "Old phone")
            .values(last_seen_at=datetime.now(UTC) - timedelta(days=31))
        )

    listed = [s["user_agent"] for s in (await api.get("/me/sessions")).json() if not s["current"]]
    revoked = (await api.post("/me/sessions:revoke-others")).json()

    assert listed == ["Tablet"]
    assert revoked == {"revoked": 1}


async def test_ending_the_current_session_signs_out(api: httpx.AsyncClient) -> None:
    [current] = (await api.get("/me/sessions")).json()

    response = await api.delete(f"/me/sessions/{current['id']}")

    assert response.status_code == 204
    assert 'penaria_session=""' in response.headers["set-cookie"]
    assert (await api.get("/me")).status_code == 401


async def test_a_session_of_another_account_cannot_be_ended(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    other = User(display_name="Neighbour", locale="en", username="neighbour")
    session, _ = Session.start(other.id, Client(user_agent=None, ip=None), datetime.now(UTC))
    async with (await uow_of(container)).transaction() as tx:
        await tx.users.add(other)
        await tx.sessions.add(session)

    response = await api.delete(f"/me/sessions/{session.id}")

    assert response.json()["code"] == "session_not_found"
    async with (await uow_of(container)).query() as tx:
        revoked_at = await tx.session.scalar(select(SessionDB.revoked_at).where(SessionDB.id == session.id))
    assert revoked_at is None


async def test_a_change_of_one_field_keeps_the_other(api: httpx.AsyncClient) -> None:
    await api.patch("/me", json={"locale": "ru"})
    response = await api.patch("/me", json={"display_name": "Alex"})

    assert matches(response.json(), account(display_name="Alex", locale="ru"))


async def test_a_hash_made_with_older_parameters_is_redone_on_sign_in(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    old = Argon2Hasher(time_cost=1, memory_cost=8192, parallelism=1).hash(OWNER["password"])
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(PasswordDB).values(hash=old))

    assert (await sign_in(new_client())).status_code == 200

    async with (await uow_of(container)).query() as tx:
        stored = await tx.session.scalar(select(PasswordDB.hash))
    assert stored is not None
    assert not Argon2Hasher().check_needs_rehash(stored)
    assert (await sign_in(new_client())).status_code == 200


@pytest.mark.parametrize("public_url", ["https://test"])
async def test_on_https_the_session_cookie_is_secure(api: httpx.AsyncClient, new_client: NewClient) -> None:
    signed_in = await sign_in(new_client())
    signed_out = await api.post("/sign-out")

    assert "Secure" in signed_in.headers["set-cookie"]
    assert "Secure" in signed_out.headers["set-cookie"]


# Limits on guessing


async def test_failures_from_one_address_block_it_for_every_username(
    api: httpx.AsyncClient, new_client: NewClient, app: FastAPI
) -> None:
    guesser = from_address(new_client, app, "192.0.2.1")
    statuses = [(await fail_to_sign_in(guesser, 1, username=f"user{n}"))[0] for n in range(5)]

    blocked = await sign_in(guesser)

    assert statuses == [401] * 5
    assert blocked.status_code == 429
    assert (await sign_in(from_address(new_client, app, "198.51.100.1"))).status_code == 200


async def test_an_ipv6_household_is_one_address(api: httpx.AsyncClient, new_client: NewClient, app: FastAPI) -> None:
    for n in range(1, 6):
        await fail_to_sign_in(from_address(new_client, app, f"2001:db8:1:2::{n}"), 1, username=f"user{n}")

    assert (await sign_in(from_address(new_client, app, "2001:db8:1:2::99"))).status_code == 429


async def test_parallel_guesses_are_counted_one_by_one(api: httpx.AsyncClient, new_client: NewClient) -> None:
    attacker = new_client()

    responses = await asyncio.gather(*(sign_in(attacker, password=WRONG) for _ in range(10)))

    assert sorted(r.status_code for r in responses) == [401] * 5 + [429] * 5


async def test_a_success_forgives_the_account_s_failures(
    api: httpx.AsyncClient, new_client: NewClient, app: FastAPI
) -> None:
    # Two addresses, so only the account's counter could reach five.
    home, office = from_address(new_client, app, "192.0.2.1"), from_address(new_client, app, "192.0.2.2")
    await fail_to_sign_in(home, 4)
    assert (await sign_in(home)).status_code == 200
    await fail_to_sign_in(office, 4)

    assert (await sign_in(office)).status_code == 200


async def test_a_success_takes_back_only_its_own_attempt_from_the_address(
    api: httpx.AsyncClient, new_client: NewClient, app: FastAPI
) -> None:
    home = from_address(new_client, app, "192.0.2.1")
    for n in range(4):
        await fail_to_sign_in(home, 1, username=f"user{n}")
    assert (await sign_in(home)).status_code == 200

    assert await fail_to_sign_in(home, 2, username="user9") == [401, 429]


async def test_a_completed_setup_takes_back_its_attempt_from_the_address(
    anonymous: httpx.AsyncClient, setup_token: str, new_client: NewClient
) -> None:
    for _ in range(4):
        await anonymous.post("/setup", json={**OWNER, "token": "0" * 32})
    assert (await anonymous.post("/setup", json={**OWNER, "token": setup_token})).status_code == 200

    assert await fail_to_sign_in(new_client(), 2, username="user9") == [401, 429]


async def test_failures_are_forgotten_after_an_hour(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    client = new_client()
    await fail_to_sign_in(client, 5)
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(
            update(SignInFailureDB).values(last_at=datetime.now(UTC) - timedelta(hours=1, minutes=1))
        )
    await fail_to_sign_in(client, 1)

    assert (await sign_in(client)).status_code == 200


async def test_wrong_current_passwords_are_limited(api: httpx.AsyncClient) -> None:
    body = {"current_password": WRONG, "new_password": NEW}
    statuses = [(await api.post("/me/password", json=body)).status_code for _ in range(5)]

    blocked = await api.post("/me/password", json={**body, "current_password": OWNER["password"]})

    assert statuses == [400] * 5
    assert blocked.status_code == 429


async def test_wrong_setup_tokens_are_limited(anonymous: httpx.AsyncClient, setup_token: str) -> None:
    statuses = [(await anonymous.post("/setup", json={**OWNER, "token": "0" * 32})).status_code for _ in range(5)]

    blocked = await anonymous.post("/setup", json={**OWNER, "token": setup_token})

    assert statuses == [403] * 5
    assert blocked.status_code == 429


async def test_of_two_setups_at_once_one_succeeds(new_client: NewClient, setup_token: str) -> None:
    first, second = await asyncio.gather(
        new_client().post("/setup", json={**OWNER, "token": setup_token}),
        new_client().post("/setup", json={**OWNER, "username": "second", "token": setup_token}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]


# The journal


async def test_account_events_are_journalled_without_a_home(
    anonymous: httpx.AsyncClient, setup_token: str, new_client: NewClient, container: DishkaContainer
) -> None:
    await anonymous.post("/setup", json={**OWNER, "token": setup_token})
    phone = new_client()
    await sign_in(phone, password=WRONG)
    await sign_in(phone)
    await anonymous.patch("/me", json={"display_name": "Alex"})
    await anonymous.post("/me/password", json={"current_password": OWNER["password"], "new_password": NEW})
    await anonymous.post("/sign-out")

    async with (await uow_of(container)).query() as tx:
        rows = (
            await tx.session.execute(
                select(
                    JournalEventDB.type, JournalEventDB.home_id, JournalEventDB.actor, JournalEventDB.payload
                ).order_by(JournalEventDB.seq)
            )
        ).all()

    user_id = rows[0].payload["user_id"]
    events = [(row.type, row.home_id, row.actor["kind"], shape(row.payload)) for row in rows]
    assert UUID_PATTERN.match(user_id)
    assert events == [
        ("account.setup_completed", None, "user", {"user_id": "uuid"}),
        ("account.signed_in", None, "user", {"user_id": "uuid", "session_id": "uuid", "ip": "127.0.0.1"}),
        ("account.sign_in_failed", None, "system", {"user_id": "uuid", "ip": "127.0.0.1"}),
        ("account.signed_in", None, "user", {"user_id": "uuid", "session_id": "uuid", "ip": "127.0.0.1"}),
        ("account.updated", None, "user", {"user_id": "uuid", "display_name": "Alex"}),
        ("account.password_changed", None, "user", {"user_id": "uuid", "sessions_ended": 1}),
        ("session.revoked", None, "user", {"user_id": "uuid", "session_id": "uuid"}),
        ("account.signed_out", None, "user", {"user_id": "uuid", "session_id": "uuid"}),
    ]
    assert {row.payload["user_id"] for row in rows} == {user_id}

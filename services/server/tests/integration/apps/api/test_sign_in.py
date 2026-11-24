"""Setup, sign-in, sessions and the account through the HTTP API, as the web app uses them."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select, update
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.features.shared.actor import Actor
from penaria.features.support.identity.domain.models import User
from penaria.features.support.identity.infra.orm import SessionDB
from penaria.features.support.identity.use_cases.homes import CreateHome
from penaria.features.support.identity.use_cases.setup import IssueSetupToken
from penaria.features.support.platform.infra.orm import JournalEventDB
from penaria.integrations.postgres.transaction import PenariaTransaction
from tests.integration.conftest import OWNER, PUBLIC_URL

pytestmark = pytest.mark.integration

NewClient = Callable[..., httpx.AsyncClient]
WRONG = "not the password"
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


async def uow_of(container: DishkaContainer) -> AsyncSQLAlchemyUnitOfWork[PenariaTransaction]:
    return await container.container.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])


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


async def test_reading_from_another_site_is_not_refused(api: httpx.AsyncClient) -> None:
    assert (await api.get("/me", headers={"origin": "https://evil.example"})).status_code == 200


# The journal


async def test_account_events_are_journalled_without_a_home(
    anonymous: httpx.AsyncClient, setup_token: str, new_client: NewClient, container: DishkaContainer
) -> None:
    await anonymous.post("/setup", json={**OWNER, "token": setup_token})
    await sign_in(new_client(), password=WRONG)
    await anonymous.post("/sign-out")

    async with (await uow_of(container)).query() as tx:
        rows = (
            await tx.session.execute(select(JournalEventDB.type, JournalEventDB.home_id, JournalEventDB.actor))
        ).all()

    assert [(type_, home_id, actor["kind"]) for type_, home_id, actor in sorted(rows)] == [
        ("account.setup_completed", None, "user"),
        ("account.sign_in_failed", None, "system"),
        ("account.signed_in", None, "user"),
        ("account.signed_out", None, "user"),
    ]

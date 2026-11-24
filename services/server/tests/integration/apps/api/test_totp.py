"""The second factor through the HTTP API: an authenticator app with recovery codes (sign-in.md, 4.3)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select, update

from penaria.apps.api.settings import Settings
from penaria.apps.cli.__main__ import parse, reset
from penaria.apps.cli.settings import Settings as CliSettings
from penaria.features.support.identity.domain.totp import code_at, step_at
from penaria.features.support.identity.infra.orm import PendingSignInDB, TotpDB
from tests.authenticator import Authenticator
from tests.integration.apps.api.test_people import age_sign_ins, invite, join, make_home, member, ok
from tests.integration.apps.api.test_recovery import FRESH, RESET_LINK, confirm_email, connect, deliver, journal
from tests.integration.conftest import OWNER, PUBLIC_URL
from tests.integration.helpers import NewClient, add_passkey, add_second_factor, from_address, uow_of
from tests.smtp import FakeSmtp, text_of

pytestmark = pytest.mark.integration

ADDRESS = "192.0.2.10"


async def enrol(client: httpx.AsyncClient) -> tuple[str, list[str]]:
    """Turn the signed-in account's authenticator app on; its secret and recovery codes."""
    started = await ok(await client.post("/me/totp"))
    secret = started["secret"]
    confirmed = await ok(await client.post("/me/totp:confirm", json={"code": now_code(secret)}))
    return secret, confirmed["codes"]


def now_code(secret: str, steps: int = 0) -> str:
    return code_at(secret, step_at(datetime.now(UTC)) + steps)


async def forget_used_codes(container: DishkaContainer) -> None:
    """As if the last code was used long ago, so the current one may be used again."""
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(TotpDB).values(last_used_step=None))


async def password_step(client: httpx.AsyncClient, password: str = OWNER["password"]) -> dict[str, Any]:
    response = await client.post("/sign-in", json={"username": "owner", "password": password})
    assert response.status_code == 202, response.text
    assert "set-cookie" not in response.headers
    return dict(response.json())


@pytest.fixture
async def secret(api: httpx.AsyncClient, container: DishkaContainer) -> str:
    """The owner, signed in as ``api``, has turned the authenticator app on; its secret. Its first code is used."""
    secret, _ = await enrol(api)
    await forget_used_codes(container)
    return secret


# Turning the app on


async def test_the_app_is_set_up_with_a_secret_and_turned_on_with_a_code(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    before = await ok(await api.get("/me/second-factor"))
    started = await ok(await api.post("/me/totp"))
    waiting = await ok(await api.get("/me/second-factor"))

    confirmed = await ok(await api.post("/me/totp:confirm", json={"code": now_code(started["secret"])}))

    uri = urlsplit(started["uri"])
    assert (uri.scheme, uri.path) == ("otpauth", "/Penaria:owner@test")
    assert parse_qs(uri.query)["secret"] == [started["secret"]]
    assert before == {
        "totp_enabled": False,
        "totp_enabled_at": None,
        "recovery_codes_left": None,
        "required": True,
        "missing": True,
    }
    assert waiting["totp_enabled"] is False
    assert len(set(confirmed["codes"])) == 10
    after = await ok(await api.get("/me/second-factor"))
    assert (after["totp_enabled"], after["recovery_codes_left"], after["missing"]) == (True, 10, False)
    assert [t for t, _ in await journal(container, "account.totp")] == ["account.totp_enabled"]


async def test_the_secret_and_the_recovery_codes_are_not_stored_as_they_are(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    secret, codes = await enrol(api)

    async with (await uow_of(container)).query() as tx:
        row = await tx.session.scalar(select(TotpDB))
    assert row is not None
    assert row.secret.startswith("pnr1:")
    assert secret not in row.secret
    assert not set(codes) & set(row.recovery_codes)


async def test_a_wrong_first_code_turns_nothing_on(api: httpx.AsyncClient) -> None:
    started = await ok(await api.post("/me/totp"))

    response = await api.post("/me/totp:confirm", json={"code": now_code(started["secret"], steps=3)})

    assert (response.status_code, response.json()["code"]) == (400, "wrong_code")
    assert (await ok(await api.get("/me/second-factor")))["totp_enabled"] is False


async def test_a_set_up_not_confirmed_in_time_must_start_again(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    started = await ok(await api.post("/me/totp"))
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(TotpDB).values(created_at=datetime.now(UTC) - timedelta(minutes=11)))

    response = await api.post("/me/totp:confirm", json={"code": now_code(started["secret"])})

    assert (response.status_code, response.json()["code"]) == (409, "totp_enrolment_not_found")


async def test_setting_the_app_up_needs_a_recent_sign_in(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    await age_sign_ins(container)

    response = await api.post("/me/totp")

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


async def test_an_app_that_is_on_is_not_set_up_again(api: httpx.AsyncClient, secret: str) -> None:
    response = await api.post("/me/totp")

    assert (response.status_code, response.json()["code"]) == (409, "totp_already_enabled")


# Signing in in two steps


async def test_signing_in_with_the_password_then_asks_for_a_code(
    secret: str, anonymous: httpx.AsyncClient, container: DishkaContainer
) -> None:
    pending = await password_step(anonymous)
    before = await anonymous.get("/me")

    signed_in = await anonymous.post(
        "/sign-in/second-factor", json={"token": pending["token"], "code": now_code(secret)}
    )

    assert before.status_code == 401
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["username"] == "owner"
    assert "penaria_session" in signed_in.headers["set-cookie"]
    assert (await ok(await anonymous.get("/me")))["username"] == "owner"
    [*_, (_, event)] = await journal(container, "account.signed_in")
    assert event["second_factor"] == "totp"


async def test_a_code_works_once(secret: str, new_client: NewClient) -> None:
    code = now_code(secret)
    first, second = new_client(), new_client()
    await ok(
        await first.post("/sign-in/second-factor", json={"token": (await password_step(first))["token"], "code": code})
    )

    again = await second.post(
        "/sign-in/second-factor", json={"token": (await password_step(second))["token"], "code": code}
    )

    assert (again.status_code, again.json()["code"]) == (400, "wrong_code")


async def test_a_pending_sign_in_opens_one_session(
    secret: str, anonymous: httpx.AsyncClient, container: DishkaContainer
) -> None:
    pending = await password_step(anonymous)
    await ok(await anonymous.post("/sign-in/second-factor", json={"token": pending["token"], "code": now_code(secret)}))
    await forget_used_codes(container)

    again = await anonymous.post("/sign-in/second-factor", json={"token": pending["token"], "code": now_code(secret)})

    assert (again.status_code, again.json()["code"]) == (401, "second_factor_expired")


async def test_a_pending_sign_in_ends_after_five_minutes(
    secret: str, anonymous: httpx.AsyncClient, container: DishkaContainer
) -> None:
    pending = await password_step(anonymous)
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(PendingSignInDB).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    response = await anonymous.post(
        "/sign-in/second-factor", json={"token": pending["token"], "code": now_code(secret)}
    )

    assert (response.status_code, response.json()["code"]) == (401, "second_factor_expired")


async def test_a_pending_sign_in_works_only_from_its_address(secret: str, new_client: NewClient, app: FastAPI) -> None:
    pending = await password_step(from_address(new_client, app, ADDRESS))

    elsewhere = from_address(new_client, app, "198.51.100.7")
    response = await elsewhere.post(
        "/sign-in/second-factor", json={"token": pending["token"], "code": now_code(secret)}
    )

    assert (response.status_code, response.json()["code"]) == (401, "second_factor_expired")


async def test_an_unknown_pending_sign_in_is_refused(secret: str, anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/sign-in/second-factor", json={"token": "made-up", "code": now_code(secret)})

    assert (response.status_code, response.json()["code"]) == (401, "second_factor_expired")


async def test_a_wrong_password_asks_for_no_code(secret: str, anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/sign-in", json={"username": "owner", "password": "not the password"})

    assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")


async def test_a_recovery_code_signs_in_once_and_is_told_by_email(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer, new_client: NewClient
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")
    _, codes = await enrol(api)
    first, second = new_client(), new_client()

    signed_in = await first.post(
        "/sign-in/second-factor", json={"token": (await password_step(first))["token"], "recovery_code": codes[0]}
    )
    again = await second.post(
        "/sign-in/second-factor", json={"token": (await password_step(second))["token"], "recovery_code": codes[0]}
    )
    await deliver(container)

    assert signed_in.status_code == 200, signed_in.text
    assert (again.status_code, again.json()["code"]) == (400, "wrong_code")
    assert (await ok(await first.get("/me/second-factor")))["recovery_codes_left"] == 9
    assert smtp.messages[-1]["Subject"] == "A recovery code was used for your Penaria account"
    assert "Recovery codes left: 9." in text_of(smtp.messages[-1])
    [(_, used)] = await journal(container, "account.recovery_code_used")
    assert used["recovery_codes_left"] == 9


async def test_a_code_and_a_recovery_code_together_are_refused(secret: str, anonymous: httpx.AsyncClient) -> None:
    pending = await password_step(anonymous)

    response = await anonymous.post(
        "/sign-in/second-factor",
        json={"token": pending["token"], "code": now_code(secret), "recovery_code": "0000-0000-0000-0000"},
    )

    assert response.status_code == 422


async def test_wrong_codes_make_the_account_wait_from_any_address(
    secret: str, new_client: NewClient, app: FastAPI, container: DishkaContainer
) -> None:
    for index in range(5):
        client = from_address(new_client, app, f"192.0.2.{20 + index}")
        pending = await password_step(client)
        wrong = await client.post("/sign-in/second-factor", json={"token": pending["token"], "code": "000000"})
        assert wrong.json()["code"] == "wrong_code"
    client = from_address(new_client, app, "192.0.2.99")
    pending = await password_step(client)

    blocked = await client.post("/sign-in/second-factor", json={"token": pending["token"], "code": now_code(secret)})

    assert (blocked.status_code, blocked.json()["code"]) == (429, "too_many_attempts")
    failed = [event for _, event in await journal(container, "account.sign_in_failed")]
    assert [event["second_factor"] for event in failed] == ["totp"] * 5


async def test_wrong_codes_make_the_address_wait(
    api: httpx.AsyncClient, secret: str, new_client: NewClient, app: FastAPI, container: DishkaContainer
) -> None:
    client = from_address(new_client, app, ADDRESS)
    tokens = [(await password_step(client))["token"] for _ in range(6)]
    for token in tokens[:5]:
        await client.post("/sign-in/second-factor", json={"token": token, "code": "000000"})
    # The account's own count is forgiven, as by a sign-in elsewhere; the address keeps its count.
    async with (await uow_of(container)).transaction() as tx:
        await tx.failures.clear(f"second-factor:{(await ok(await api.get('/me')))['id']}")

    blocked = await client.post("/sign-in/second-factor", json={"token": tokens[5], "code": now_code(secret)})

    assert (blocked.status_code, blocked.json()["code"]) == (429, "too_many_attempts")


async def test_a_passkey_signs_in_without_a_code(
    api: httpx.AsyncClient, secret: str, anonymous: httpx.AsyncClient
) -> None:
    phone = await add_second_factor(api, PUBLIC_URL)
    ceremony = await ok(await anonymous.post("/sign-in/passkey/options"))

    response = await anonymous.post(
        "/sign-in/passkey",
        json={"challenge_id": ceremony["challenge_id"], "credential": phone.get(ceremony["options"])},
    )

    assert response.status_code == 200, response.text


async def test_a_password_reset_keeps_the_second_factor(
    api: httpx.AsyncClient, secret: str, settings: Settings, anonymous: httpx.AsyncClient
) -> None:
    printed = await reset(
        CliSettings.model_validate({"database": settings.database, "public_url": PUBLIC_URL}),
        parse(["users", "reset", "owner"]),
    )
    [token] = RESET_LINK.findall(printed)
    await ok(await anonymous.post("/password-reset", json={"token": token, "new_password": FRESH}), 204)

    response = await anonymous.post("/sign-in", json={"username": "owner", "password": FRESH})

    assert response.status_code == 202


async def test_the_operator_turns_the_app_off_for_a_person_who_lost_it(
    api: httpx.AsyncClient, secret: str, settings: Settings, anonymous: httpx.AsyncClient, container: DishkaContainer
) -> None:
    cli = CliSettings.model_validate({"database": settings.database, "public_url": PUBLIC_URL})

    printed = await reset(cli, parse(["users", "reset", "owner", "--disable-second-factor"]))
    [token] = RESET_LINK.findall(printed)
    await ok(await anonymous.post("/password-reset", json={"token": token, "new_password": FRESH}), 204)

    assert "Its authenticator app is turned off" in printed
    signed_in = await anonymous.post("/sign-in", json={"username": "owner", "password": FRESH})
    assert signed_in.status_code == 200
    assert (await ok(await anonymous.get("/me/second-factor")))["missing"] is True
    [(_, event)] = await journal(container, "account.totp_disabled")
    assert event["by"] == "operator"


# Confirming it is you


async def test_confirming_with_the_password_asks_for_a_code_too(
    api: httpx.AsyncClient, secret: str, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    alone = await api.post("/me/reauthenticate", json={"password": OWNER["password"]})
    wrong = await api.post("/me/reauthenticate", json={"password": OWNER["password"], "code": now_code(secret, 3)})
    right = await api.post("/me/reauthenticate", json={"password": OWNER["password"], "code": now_code(secret)})

    assert (alone.status_code, alone.json()["code"]) == (400, "second_factor_code_required")
    assert (wrong.status_code, wrong.json()["code"]) == (400, "wrong_code")
    assert right.status_code == 204
    assert (await api.post("/me/totp/recovery-codes")).status_code == 200
    [*_, (_, event)] = await journal(container, "account.reauthenticated")
    assert event["second_factor"] == "totp"


async def test_confirming_with_a_recovery_code(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    _, codes = await enrol(api)
    await age_sign_ins(container)

    response = await api.post("/me/reauthenticate", json={"password": OWNER["password"], "recovery_code": codes[1]})

    assert response.status_code == 204
    assert (await ok(await api.get("/me/second-factor")))["recovery_codes_left"] == 9


# Recovery codes and turning the app off


async def test_new_recovery_codes_replace_the_old_ones(
    api: httpx.AsyncClient, container: DishkaContainer, new_client: NewClient
) -> None:
    _, old = await enrol(api)

    new = (await ok(await api.post("/me/totp/recovery-codes")))["codes"]
    client = new_client()
    refused = await client.post(
        "/sign-in/second-factor", json={"token": (await password_step(client))["token"], "recovery_code": old[0]}
    )
    accepted = await client.post(
        "/sign-in/second-factor", json={"token": (await password_step(client))["token"], "recovery_code": new[0]}
    )

    assert not set(old) & set(new)
    assert refused.json()["code"] == "wrong_code"
    assert accepted.status_code == 200
    assert [t for t, _ in await journal(container, "account.recovery_codes")] == ["account.recovery_codes_regenerated"]


async def test_new_recovery_codes_need_a_recent_sign_in(
    api: httpx.AsyncClient, secret: str, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await api.post("/me/totp/recovery-codes")

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


async def test_an_owner_without_a_passkey_keeps_the_app(api: httpx.AsyncClient, secret: str) -> None:
    response = await api.delete("/me/totp")

    assert (response.status_code, response.json()["code"]) == (409, "last_second_factor")
    assert (await ok(await api.get("/me/second-factor")))["totp_enabled"] is True


async def test_an_owner_with_a_passkey_turns_the_app_off(
    api: httpx.AsyncClient, secret: str, container: DishkaContainer, anonymous: httpx.AsyncClient
) -> None:
    await add_second_factor(api, PUBLIC_URL)

    await ok(await api.delete("/me/totp"), 204)

    assert (
        await anonymous.post("/sign-in", json={"username": "owner", "password": OWNER["password"]})
    ).status_code == 200
    assert [t for t, _ in await journal(container, "account.totp_disabled")] == ["account.totp_disabled"]


async def test_turning_the_app_off_needs_a_recent_sign_in(
    api: httpx.AsyncClient, secret: str, container: DishkaContainer
) -> None:
    await age_sign_ins(container)

    response = await api.delete("/me/totp")

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


async def test_a_member_who_is_no_owner_turns_the_app_off(api: httpx.AsyncClient, new_client: NewClient) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    await enrol(maria)

    await ok(await maria.delete("/me/totp"), 204)

    assert await ok(await maria.get("/me/second-factor")) == {
        "totp_enabled": False,
        "totp_enabled_at": None,
        "recovery_codes_left": None,
        "required": False,
        "missing": False,
    }


async def test_turning_on_and_off_and_new_codes_are_told_by_email(
    api: httpx.AsyncClient, smtp: FakeSmtp, container: DishkaContainer
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    await connect(api, smtp)
    await confirm_email(api, smtp, container, "owner@example.org")

    await enrol(api)
    await ok(await api.post("/me/totp/recovery-codes"))
    await ok(await api.delete("/me/totp"), 204)
    await deliver(container)

    assert [message["Subject"] for message in smtp.messages[-3:]] == [
        "Two-step sign-in is on for your Penaria account",
        "New recovery codes for your Penaria account",
        "Two-step sign-in is off for your Penaria account",
    ]


# Who must have a second factor


async def test_an_owner_without_a_second_factor_cannot_hand_the_home_over(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}

    refused = await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": roles["owner"]})
    family = await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": roles["family"]})

    assert (refused.status_code, refused.json()["code"]) == (403, "second_factor_required")
    assert family.status_code == 201


async def test_an_owner_without_a_second_factor_changes_nobodys_access(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    [person] = [
        m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if m["person"]["username"] == "maria"
    ]
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}
    maria_id = (await ok(await maria.get("/me")))["id"]

    changed = await api.patch(
        f"/homes/{ids['home']}/grants/{person['grants'][0]['id']}", json={"role_id": roles["admin"]}
    )
    reset_link = await api.post(f"/homes/{ids['home']}/members/{maria_id}:reset-link")

    assert (changed.status_code, changed.json()["code"]) == (403, "second_factor_required")
    assert (reset_link.status_code, reset_link.json()["code"]) == (403, "second_factor_required")


async def test_an_install_admin_without_a_second_factor_sees_no_settings(api: httpx.AsyncClient) -> None:
    response = await api.get("/install/mail")

    assert (response.status_code, response.json()["code"]) == (403, "second_factor_required")


async def test_the_app_lifts_the_refusal_at_once(api: httpx.AsyncClient) -> None:
    await enrol(api)

    response = await api.get("/install/mail")

    assert response.status_code == 200


async def test_a_new_owner_must_add_a_second_factor_too(api: httpx.AsyncClient, new_client: NewClient) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    family = await member(api, new_client, ids["home"], "family", "maria")
    before = await ok(await family.get("/me/second-factor"))
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}
    transfer = await ok(await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": roles["owner"]}), 201)

    owner = await join(new_client, transfer["url"].rsplit("/", 1)[1], "ivan")

    assert (before["required"], before["missing"]) == (False, False)
    after = await ok(await owner.get("/me/second-factor"))
    assert (after["required"], after["missing"]) == (True, True)


async def test_a_passkey_counts_as_the_second_factor(api: httpx.AsyncClient) -> None:
    await ok(await add_passkey(api, Authenticator(PUBLIC_URL)), 201)

    status = await ok(await api.get("/me/second-factor"))

    assert (status["required"], status["missing"]) == (True, False)
    assert (await api.get("/install/mail")).status_code == 200


async def test_an_owner_without_a_second_factor_may_still_leave(api: httpx.AsyncClient, new_client: NewClient) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    roles = {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{ids['home']}/roles"))}
    second = await ok(await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": roles["owner"]}), 201)
    ivan = await join(new_client, second["url"].rsplit("/", 1)[1], "ivan")

    await ok(await ivan.post(f"/homes/{ids['home']}:leave"), 204)


async def test_invitations_of_other_roles_need_no_second_factor(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)

    token = await invite(api, ids["home"], "admin")

    assert token

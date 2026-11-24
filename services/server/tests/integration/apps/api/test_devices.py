"""Devices and integrations through the HTTP API: their tokens, what they reach, and how they end."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import update

from penaria.features.support.identity.domain.models import Role
from penaria.features.support.identity.infra.orm import TokenDB
from tests.integration.apps.api.test_people import (
    age_sign_ins,
    event_types,
    invite_role,
    join,
    last_events,
    later,
    make_home,
    member,
    ok,
    roles,
)
from tests.integration.conftest import PUBLIC_URL
from tests.integration.helpers import NewClient, add_second_factor, from_address, uow_of

pytestmark = pytest.mark.integration

UNKNOWN = "pnr_" + "x" * 43
EVIL = {"origin": "https://evil.example"}


async def add_device(
    client: httpx.AsyncClient, home_id: str, preset: str = "family", name: str = "Hallway mirror", **body: Any
) -> dict[str, Any]:
    """A new device of the home, with its token."""
    role_id = (await roles(client, home_id))[preset]
    created: dict[str, Any] = await ok(
        await client.post(f"/homes/{home_id}/devices", json={"name": name, "role_id": role_id, **body}), 201
    )
    return created


def bearer(new_client: NewClient, token: str, **kwargs: Any) -> httpx.AsyncClient:
    """A script that sends the token with every request and keeps no cookies."""
    return new_client(headers={"authorization": f"Bearer {token}"}, **kwargs)


async def children(client: httpx.AsyncClient, home_id: str, parent_id: str | None = None) -> httpx.Response:
    params = {} if parent_id is None else {"parent_id": parent_id}
    return await client.get(f"/homes/{home_id}/entities", params=params)


# Making devices


async def test_a_device_is_made_with_a_token_shown_once_and_listed_without_it(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)

    created = await add_device(api, ids["home"], "contractor", "Backup script", scope_entity_id=ids["house"])
    listed = await ok(await api.get(f"/homes/{ids['home']}/devices"))

    assert created["token"].startswith("pnr_")
    assert len(created["token"]) == 47
    assert listed == [created["device"]]
    assert {key: listed[0][key] for key in ("name", "last_used_at", "last_used_ip")} == {
        "name": "Backup script",
        "last_used_at": None,
        "last_used_ip": None,
    }
    assert (listed[0]["role"]["preset"], listed[0]["scope"]["names"], listed[0]["granted_by"]["username"]) == (
        "contractor",
        ["Country house", "House"],
        "owner",
    )


async def test_making_a_device_needs_a_recent_sign_in(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    ids = await make_home(api)
    family = (await roles(api, ids["home"]))["family"]
    await age_sign_ins(container)

    response = await api.post(f"/homes/{ids['home']}/devices", json={"name": "Mirror", "role_id": family})

    assert (response.status_code, response.json()["code"]) == (403, "recent_sign_in_required")


@pytest.mark.parametrize("preset", ["owner", "guest"])
async def test_a_device_gets_no_owner_role_nor_one_whose_access_must_end(api: httpx.AsyncClient, preset: str) -> None:
    ids = await make_home(api)
    role_id = (await roles(api, ids["home"]))[preset]

    response = await api.post(f"/homes/{ids['home']}/devices", json={"name": "Mirror", "role_id": role_id})

    assert response.status_code == 400
    assert (response.json()["code"], response.json()["params"]) == (
        "invalid_grant",
        {"field": "role_id", "reason": "device_role"},
    )


async def test_a_family_member_cannot_make_or_see_devices(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    family = (await roles(maria, ids["home"]))["family"]

    made = await maria.post(f"/homes/{ids['home']}/devices", json={"name": "Mirror", "role_id": family})
    listed = await maria.get(f"/homes/{ids['home']}/devices")

    assert (made.status_code, made.json()["code"]) == (403, "permission_denied")
    assert (listed.status_code, listed.json()["code"]) == (403, "permission_denied")


async def test_a_device_gets_no_more_than_its_maker_holds(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    # A custom role that manages people but changes nothing in the tree.
    doorkeeper = Role(
        home_id=UUID(ids["home"]),
        preset=None,
        name="Doorkeeper",
        all_permissions=False,
        permissions=frozenset({"members.manage", "entities.view"}),
    )
    async with (await uow_of(container)).transaction() as tx:
        await tx.roles.add_all([doorkeeper])
    keeper = await join(new_client, await invite_role(api, ids["home"], str(doorkeeper.id)), "keeper")

    refused = await keeper.post(
        f"/homes/{ids['home']}/devices",
        json={"name": "Mirror", "role_id": (await roles(keeper, ids["home"]))["family"]},
    )
    allowed = await keeper.post(f"/homes/{ids['home']}/devices", json={"name": "Mirror", "role_id": str(doorkeeper.id)})

    assert (refused.status_code, refused.json()["code"]) == (403, "escalation")
    assert allowed.status_code == 201


# What a device reaches


async def test_a_device_reads_and_changes_the_home_within_its_role(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    mirror = bearer(new_client, (await add_device(api, ids["home"], "family"))["token"])

    homes = await ok(await mirror.get("/homes"))
    created = await ok(
        await mirror.post(
            f"/homes/{ids['home']}/entities", json={"kind": "item", "name": "Umbrella", "parent_id": ids["kitchen"]}
        ),
        201,
    )

    assert [home["name"] for home in homes] == ["Country house"]
    assert created["name"] == "Umbrella"
    assert (await last_events(container, 1))[0][:2] == ("entity.created", "device")


async def test_a_device_does_only_what_its_role_allows(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    script = bearer(new_client, (await add_device(api, ids["home"], "contractor"))["token"])

    read = await children(script, ids["home"], ids["house"])
    edit = await script.post(
        f"/homes/{ids['home']}/entities", json={"kind": "item", "name": "Umbrella", "parent_id": ids["kitchen"]}
    )

    assert read.status_code == 200
    assert (edit.status_code, edit.json()["code"]) == (403, "permission_denied")


async def test_a_device_over_a_place_reaches_only_inside_it(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    token = (await add_device(api, ids["home"], "family", scope_entity_id=ids["guest_room"]))["token"]
    mirror = bearer(new_client, token)

    inside = await mirror.get(f"/entities/{ids['towels']}")
    outside = await mirror.get(f"/entities/{ids['kitchen']}")

    assert inside.status_code == 200
    assert outside.status_code == 404


async def test_a_device_reaches_no_account_people_or_install_endpoint(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    # Even a device with every permission of the home.
    script = bearer(new_client, (await add_device(api, ids["home"], "admin"))["token"])

    answers = {
        "me": await script.get("/me"),
        "sessions": await script.get("/me/sessions"),
        "sign_out": await script.post("/sign-out"),
        "members": await script.get(f"/homes/{ids['home']}/members"),
        "devices": await script.get(f"/homes/{ids['home']}/devices"),
        "mailbox": await script.get("/install/mail"),
        "guest": await script.get("/guest"),
    }
    new_home = await script.post("/homes", json={"name": "Mine", "timezone": "UTC", "locale": "en"})

    assert {name: (r.status_code, r.json()["code"]) for name, r in answers.items()} == dict.fromkeys(
        answers, (401, "unauthenticated")
    )
    assert (new_home.status_code, new_home.json()["code"]) == (403, "account_required")


async def test_a_bearer_request_is_judged_by_its_token_not_its_cookie(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    token = (await add_device(api, ids["home"], "contractor"))["token"]

    # The owner's browser sends its cookie along: the request still acts as the device.
    edit = await api.post(
        f"/homes/{ids['home']}/entities",
        json={"kind": "item", "name": "Umbrella", "parent_id": ids["kitchen"]},
        headers={"authorization": f"Bearer {token}"},
    )
    me = await api.get("/me", headers={"authorization": f"Bearer {token}"})

    assert (edit.status_code, edit.json()["code"]) == (403, "permission_denied")
    assert (me.status_code, me.json()["code"]) == (401, "unauthenticated")


async def test_a_bearer_request_is_not_refused_for_its_origin(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    mirror = bearer(new_client, (await add_device(api, ids["home"]))["token"])

    response = await mirror.post(
        f"/homes/{ids['home']}/entities",
        json={"kind": "item", "name": "Umbrella", "parent_id": ids["kitchen"]},
        headers=EVIL,
    )

    assert response.status_code == 201


@pytest.mark.parametrize("authorization", ["Basic dXNlcjpwYXNz", "Bearer a-reverse-proxys-own-token"])
async def test_another_authorization_header_leaves_the_request_to_its_cookie(
    api: httpx.AsyncClient, authorization: str
) -> None:
    me = await api.get("/me", headers={"authorization": authorization})
    cross_site = await api.post(
        "/homes",
        json={"name": "Flat", "timezone": "UTC", "locale": "en"},
        headers={"authorization": authorization, **EVIL},
    )

    assert me.status_code == 200
    assert (cross_site.status_code, cross_site.json()["code"]) == (403, "cross_origin_request")


async def test_an_unknown_token_is_refused(new_client: NewClient) -> None:
    response = await bearer(new_client, UNKNOWN).get("/homes")

    assert (response.status_code, response.json()["code"]) == (401, "invalid_token")


async def test_a_malformed_token_is_refused(new_client: NewClient) -> None:
    response = await bearer(new_client, "pnr_short").get("/homes")

    assert (response.status_code, response.json()["code"]) == (401, "invalid_token")


async def test_unknown_and_malformed_tokens_make_the_address_wait(
    api: httpx.AsyncClient, new_client: NewClient, app: Any
) -> None:
    ids = await make_home(api)
    valid = (await add_device(api, ids["home"]))["token"]
    guesser = from_address(new_client, app, "203.0.113.5")
    elsewhere = from_address(new_client, app, "198.51.100.9")
    elsewhere.headers["authorization"] = f"Bearer {UNKNOWN}"

    guesses = [UNKNOWN, "pnr_short", UNKNOWN, "pnr_short", UNKNOWN]
    statuses = [
        (await guesser.get("/homes", headers={"authorization": f"Bearer {guess}"})).status_code for guess in guesses
    ]
    blocked = await guesser.get("/homes", headers={"authorization": f"Bearer {UNKNOWN}"})
    # The address must wait: a valid token from it waits too (sign-in.md, 17).
    valid_from_there = await guesser.get("/homes", headers={"authorization": f"Bearer {valid}"})
    # Signing in from the same address is limited apart.
    signing_in = await guesser.post("/sign-in", json={"username": "owner", "password": "not the password"})

    assert statuses == [401] * 5
    assert (blocked.status_code, blocked.json()["code"]) == (429, "too_many_attempts")
    assert (valid_from_there.status_code, valid_from_there.json()["code"]) == (429, "too_many_attempts")
    assert (signing_in.status_code, signing_in.json()["code"]) == (401, "invalid_credentials")
    assert (await elsewhere.get("/homes")).json()["code"] == "invalid_token"


async def test_a_revoked_device_calling_on_does_not_make_its_address_wait(
    api: httpx.AsyncClient, new_client: NewClient, app: Any
) -> None:
    ids = await make_home(api)
    old = await add_device(api, ids["home"], name="Old mirror")
    new = await add_device(api, ids["home"], name="New mirror")
    await ok(await api.delete(f"/homes/{ids['home']}/grants/{old['device']['grant_id']}"), 204)
    forgotten = from_address(new_client, app, "203.0.113.5")
    forgotten.headers["authorization"] = f"Bearer {old['token']}"
    neighbour = from_address(new_client, app, "203.0.113.5")
    neighbour.headers["authorization"] = f"Bearer {new['token']}"

    statuses = [(await forgotten.get("/homes")).status_code for _ in range(10)]

    assert statuses == [401] * 10
    assert (await neighbour.get("/homes")).status_code == 200


# How a device ends


async def test_revoking_a_device_ends_its_access_at_once(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    created = await add_device(api, ids["home"])
    mirror = bearer(new_client, created["token"])
    await ok(await mirror.get("/homes"))

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{created['device']['grant_id']}"), 204)

    refused = await mirror.get("/homes")
    assert (refused.status_code, refused.json()["code"]) == (401, "invalid_token")
    assert await ok(await api.get(f"/homes/{ids['home']}/devices")) == []
    assert (await last_events(container, 1))[0] == (
        "device.revoked",
        "user",
        {"device_id": "uuid", "grant_id": "uuid", "reason": "revoked"},
    )


async def test_a_device_ends_when_its_maker_loses_access(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    mirror = bearer(new_client, (await add_device(admin, ids["home"]))["token"])
    [anna] = [m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if m["person"]["username"] == "anna"]

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{anna['grants'][0]['id']}"), 204)

    assert (await mirror.get("/homes")).status_code == 401
    assert await ok(await api.get(f"/homes/{ids['home']}/devices")) == []
    assert (await last_events(container, 1))[0] == (
        "device.revoked",
        "user",
        {"device_id": "uuid", "grant_id": "uuid", "reason": "giver_lost_access"},
    )


async def test_access_that_ends_cannot_give_a_device_whose_access_never_does(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    sitter = await member(api, new_client, ids["home"], "admin", "sitter", grant_expires_at=later(days=7))
    family = (await roles(sitter, ids["home"]))["family"]

    response = await sitter.post(f"/homes/{ids['home']}/devices", json={"name": "Mirror", "role_id": family})

    assert (response.status_code, response.json()["code"]) == (403, "giver_access_ends")


async def test_a_device_ends_when_its_makers_access_is_given_an_end(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    mirror = bearer(new_client, (await add_device(admin, ids["home"]))["token"])
    [anna] = [m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if m["person"]["username"] == "anna"]

    await ok(
        await api.patch(f"/homes/{ids['home']}/grants/{anna['grants'][0]['id']}", json={"expires_at": later(days=7)}),
        204,
    )

    assert (await mirror.get("/homes")).json()["code"] == "invalid_token"
    assert (await last_events(container, 1))[0][2]["reason"] == "giver_lost_access"


async def test_a_devices_access_is_not_changed(api: httpx.AsyncClient) -> None:
    await add_second_factor(api, PUBLIC_URL)
    ids = await make_home(api)
    created = await add_device(api, ids["home"])
    contractor = (await roles(api, ids["home"]))["contractor"]

    response = await api.patch(
        f"/homes/{ids['home']}/grants/{created['device']['grant_id']}", json={"role_id": contractor}
    )

    assert (response.status_code, response.json()["code"]) == (400, "invalid_grant")


async def test_a_device_is_not_a_member(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    await add_device(api, ids["home"])

    members = await ok(await api.get(f"/homes/{ids['home']}/members"))

    assert [m["person"]["username"] for m in members] == ["owner"]


# Its use and the journal


async def age_last_use(container: DishkaContainer, age: timedelta) -> None:
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(TokenDB).values(last_used_at=datetime.now(UTC) - age))


async def test_the_list_shows_when_and_from_where_a_device_was_last_used(
    api: httpx.AsyncClient, new_client: NewClient, app: Any
) -> None:
    ids = await make_home(api)
    created = await add_device(api, ids["home"])
    mirror = from_address(new_client, app, "192.0.2.44")
    mirror.headers["authorization"] = f"Bearer {created['token']}"

    await ok(await mirror.get("/homes"))

    [listed] = await ok(await api.get(f"/homes/{ids['home']}/devices"))
    assert listed["last_used_ip"] == "192.0.2.44"
    assert datetime.fromisoformat(listed["last_used_at"]) > datetime.now(UTC) - timedelta(minutes=1)


async def test_making_using_and_revoking_a_device_is_journalled_without_a_line_per_request(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer, app: Any
) -> None:
    ids = await make_home(api)
    created = await add_device(api, ids["home"], "contractor")
    mirror = from_address(new_client, app, "192.0.2.44")
    mirror.headers["authorization"] = f"Bearer {created['token']}"
    moved = from_address(new_client, app, "198.51.100.9")
    moved.headers["authorization"] = f"Bearer {created['token']}"

    for _ in range(3):
        await ok(await mirror.get("/homes"))
    # Another address minutes later is journalled when the use is next recorded, not on every request.
    await ok(await moved.get("/homes"))
    await age_last_use(container, timedelta(minutes=6))
    await ok(await moved.get("/homes"))
    await age_last_use(container, timedelta(days=1))
    await ok(await moved.get("/homes"))
    await ok(await api.delete(f"/homes/{ids['home']}/grants/{created['device']['grant_id']}"), 204)

    assert (await event_types(container))[-5:] == [
        "device.created",
        "device.used",
        "device.used",
        "device.used",
        "device.revoked",
    ]
    assert (await last_events(container, 5))[0] == (
        "device.created",
        "user",
        {
            "grant_id": "uuid",
            "principal_type": "device",
            "principal_id": "uuid",
            "role_id": "uuid",
            "role": "contractor",
            "scope_entity_id": None,
            "expires_at": None,
            "device_id": "uuid",
            "name": "Hallway mirror",
        },
    )
    assert (await last_events(container, 4))[0] == ("device.used", "device", {"device_id": "uuid", "ip": "192.0.2.44"})


async def test_the_list_shows_only_this_homes_devices_the_newest_first(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    flat = await make_home(api, "Flat")
    dacha = await make_home(api, "Dacha")
    guest = (await roles(api, flat["home"]))["guest"]
    await ok(await api.post(f"/homes/{flat['home']}/guest-links", json={"name": "Weekend", "role_id": guest}), 201)
    await add_device(api, flat["home"], name="Mirror")
    await add_device(api, flat["home"], name="Backup script")
    await add_device(api, dacha["home"], name="Thermometer")

    listed = await ok(await api.get(f"/homes/{flat['home']}/devices"))

    assert [device["name"] for device in listed] == ["Backup script", "Mirror"]

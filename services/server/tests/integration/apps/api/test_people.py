"""People in a home through the HTTP API: invitations, members, ownership and guest links."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import func, select, update

from penaria.features.support.identity.domain.models import Role
from penaria.features.support.identity.infra.orm import GrantDB, InvitationDB, SessionDB
from penaria.features.support.identity.use_cases import guest_links
from penaria.features.support.platform.infra.orm import JournalEventDB
from tests.integration.conftest import PUBLIC_URL
from tests.integration.helpers import NewClient, shape, uow_of

pytestmark = pytest.mark.integration

CHOSEN = "a long family password"


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def make_home(api: httpx.AsyncClient, name: str = "Country house") -> dict[str, str]:
    """A home with a house, a guest room with towels in it, and a private study."""
    home = await ok(await api.post("/homes", json={"name": name, "timezone": "Europe/Moscow", "locale": "en"}), 201)
    home_id = home["id"]

    async def add(body: dict[str, Any]) -> str:
        entity = await ok(await api.post(f"/homes/{home_id}/entities", json=body), 201)
        return str(entity["id"])

    plot = await add({"kind": "property", "name": name})
    house = await add({"kind": "building", "name": "House", "parent_id": plot})
    guest_room = await add({"kind": "space", "name": "Guest room", "parent_id": house})
    towels = await add({"kind": "item", "name": "Towels", "parent_id": guest_room, "privacy": "guest_visible"})
    study = await add({"kind": "space", "name": "Study", "parent_id": house, "privacy": "private"})
    kitchen = await add({"kind": "space", "name": "Kitchen", "parent_id": house})
    return {
        "home": home_id,
        "plot": plot,
        "house": house,
        "guest_room": guest_room,
        "towels": towels,
        "study": study,
        "kitchen": kitchen,
    }


async def roles(api: httpx.AsyncClient, home_id: str) -> dict[str, str]:
    """The home's preset roles' ids, by preset."""
    return {role["preset"]: role["id"] for role in await ok(await api.get(f"/homes/{home_id}/roles"))}


async def invite(api: httpx.AsyncClient, home_id: str, preset: str, **body: Any) -> str:
    """A new invitation's token."""
    role_id = (await roles(api, home_id))[preset]
    created = await ok(await api.post(f"/homes/{home_id}/invitations", json={"role_id": role_id, **body}), 201)
    url: str = created["url"]
    prefix = f"{PUBLIC_URL}/invite/"
    assert url.startswith(prefix)
    return url.removeprefix(prefix)


async def join(new_client: NewClient, token: str, username: str) -> httpx.AsyncClient:
    """A new browser that makes an account through the invitation."""
    client = new_client()
    body = {"token": token, "username": username, "display_name": username.title(), "password": CHOSEN}
    await ok(await client.post("/invitations:accept-new-account", json={**body, "locale": "en"}))
    return client


async def member(
    api: httpx.AsyncClient, new_client: NewClient, home_id: str, preset: str, username: str, **body: Any
) -> httpx.AsyncClient:
    return await join(new_client, await invite(api, home_id, preset, **body), username)


def later(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


async def age_sign_ins(container: DishkaContainer) -> None:
    """Every session last proved its person eleven minutes ago, too long for a sensitive change."""
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(SessionDB).values(authenticated_at=datetime.now(UTC) - timedelta(minutes=11)))


async def home_names(client: httpx.AsyncClient) -> list[str]:
    return [home["name"] for home in await ok(await client.get("/homes"))]


async def event_types(container: DishkaContainer) -> list[str]:
    async with (await uow_of(container)).query() as tx:
        return list(await tx.session.scalars(select(JournalEventDB.type).order_by(JournalEventDB.seq)))


# Invitations


async def test_a_new_account_joins_through_an_invitation_and_lands_in_the_home(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    newcomer = new_client()

    preview = await ok(await newcomer.post("/invitations:preview", json={"token": token}))
    joined = await ok(
        await newcomer.post(
            "/invitations:accept-new-account",
            json={"token": token, "username": "Maria", "display_name": "Maria", "password": CHOSEN, "locale": "ru"},
        )
    )

    assert (preview["home"]["name"], preview["inviter"], preview["role"]["preset"]) == (
        "Country house",
        "Owner",
        "family",
    )
    assert preview["scope"] is None
    assert joined["account"]["username"] == "maria"
    assert joined["account"]["locale"] == "ru"
    assert joined["account"]["install_admin"] is False
    assert joined["home"] == {"id": ids["home"], "name": "Country house"}
    assert await home_names(newcomer) == ["Country house"]
    assert (await ok(await newcomer.get(f"/homes/{ids['home']}")))["access"]["owner"] is False


async def test_an_existing_account_accepts_an_invitation_to_another_home(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    flat = await make_home(api, "Flat")
    maria = await member(api, new_client, flat["home"], "family", "maria")
    # Maria's parents' house, of another owner: one account, many homes.
    parents_owner = await member(api, new_client, flat["home"], "admin", "parent")
    parents = await make_home(parents_owner, "Parents' house")
    token = await invite(parents_owner, parents["home"], "guest")

    accepted = await ok(await maria.post("/invitations:accept", json={"token": token}))

    assert accepted == {"id": parents["home"], "name": "Parents' house"}
    assert await home_names(maria) == ["Flat", "Parents' house"]


async def test_an_invitation_works_once(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    await join(new_client, token, "maria")

    again = await new_client().post("/invitations:preview", json={"token": token})

    assert again.status_code == 409
    assert again.json()["code"] == "invitation_used"


async def test_an_expired_invitation_is_refused(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(InvitationDB).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))

    response = await new_client().post("/invitations:preview", json={"token": token})

    assert response.json()["code"] == "invitation_expired"


async def test_a_revoked_invitation_is_refused_and_leaves_the_list(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    [pending] = await ok(await api.get(f"/homes/{ids['home']}/invitations"))

    await ok(await api.delete(f"/homes/{ids['home']}/invitations/{pending['id']}"), 204)

    response = await new_client().post("/invitations:preview", json={"token": token})
    assert response.json()["code"] == "invitation_revoked"
    assert await ok(await api.get(f"/homes/{ids['home']}/invitations")) == []


async def test_an_unknown_invitation_is_not_found(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/invitations:preview", json={"token": "not-a-real-token"})

    assert response.status_code == 404
    assert response.json()["code"] == "invitation_not_found"


async def test_guessing_invitation_tokens_makes_the_address_wait(new_client: NewClient) -> None:
    guesser = new_client()
    statuses = [
        (await guesser.post("/invitations:preview", json={"token": f"guess-{n}"})).status_code for n in range(6)
    ]

    assert statuses == [404, 404, 404, 404, 404, 429]
    # Signing in from the same address is limited apart.
    signing_in = await guesser.post("/sign-in", json={"username": "owner", "password": "not the password"})
    assert signing_in.json()["code"] == "invalid_credentials"


async def test_a_pending_invitation_shows_who_made_it_and_what_it_gives(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    await invite(api, ids["home"], "contractor", scope_entity_id=ids["kitchen"])

    [pending] = await ok(await api.get(f"/homes/{ids['home']}/invitations"))

    assert pending["role"]["preset"] == "contractor"
    assert pending["scope"] == {"id": ids["kitchen"], "names": ["Country house", "House", "Kitchen"]}
    assert pending["created_by"]["display_name"] == "Owner"
    assert pending["grant_expires_at"] is None
    assert pending["leave_when_accepted"] is False


async def test_an_invitation_lasts_seven_days_and_never_outlives_its_access(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    await invite(api, ids["home"], "family")
    await invite(api, ids["home"], "guest")

    guest, family = await ok(await api.get(f"/homes/{ids['home']}/invitations"))

    lasts = {
        invitation["role"]["preset"]: datetime.fromisoformat(invitation["expires_at"])
        - datetime.fromisoformat(invitation["created_at"])
        for invitation in (guest, family)
    }
    assert lasts == {"family": timedelta(days=7), "guest": timedelta(days=3)}
    assert guest["grant_expires_at"] == guest["expires_at"]


async def test_an_invitation_lasting_longer_than_thirty_days_is_refused(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    role_id = (await roles(api, ids["home"]))["family"]

    response = await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": role_id, "valid_days": 31})

    assert (response.status_code, response.json()["code"]) == (422, "validation_error")


async def test_an_invitation_lasts_the_days_asked_for(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    await invite(api, ids["home"], "family", valid_days=30)

    [pending] = await ok(await api.get(f"/homes/{ids['home']}/invitations"))

    lasts = datetime.fromisoformat(pending["expires_at"]) - datetime.fromisoformat(pending["created_at"])
    assert lasts == timedelta(days=30)


async def test_a_guest_invitation_gives_access_that_ends(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    await member(api, new_client, ids["home"], "guest", "sergey")

    members = await ok(await api.get(f"/homes/{ids['home']}/members"))

    [sergey] = [m for m in members if m["person"]["username"] == "sergey"]
    [grant] = sergey["grants"]
    assert grant["expires_at"] is not None
    assert grant["granted_by"]["display_name"] == "Owner"


async def test_accepting_your_own_invitation_is_refused(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")

    response = await api.post("/invitations:accept", json={"token": token})

    assert response.json()["code"] == "own_invitation"


async def test_accepting_access_you_already_have_keeps_the_invitation(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    token = await invite(api, ids["home"], "family")

    refused = await maria.post("/invitations:accept", json={"token": token})

    assert refused.json()["code"] == "already_granted"
    assert (await new_client().post("/invitations:preview", json={"token": token})).status_code == 200


async def test_a_taken_username_is_refused_and_the_invitation_kept(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "family")
    body = {"token": token, "username": "Owner", "display_name": "Impostor", "password": CHOSEN, "locale": "en"}

    response = await new_client().post("/invitations:accept-new-account", json=body)

    assert response.status_code == 409
    assert response.json()["code"] == "username_taken"
    assert (await new_client().post("/invitations:preview", json={"token": token})).status_code == 200


async def test_accepting_is_journalled(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    await member(api, new_client, ids["home"], "family", "maria")

    types = await event_types(container)

    assert types[-5:] == [
        "invitation.created",
        "account.created",
        "invitation.accepted",
        "grant.created",
        "account.signed_in",
    ]


# No escalation


async def test_a_family_member_cannot_invite(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    role_id = (await roles(maria, ids["home"]))["guest"]

    response = await maria.post(f"/homes/{ids['home']}/invitations", json={"role_id": role_id})

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_an_admin_cannot_make_owners(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    role_id = (await roles(admin, ids["home"]))["owner"]

    response = await admin.post(f"/homes/{ids['home']}/invitations", json={"role_id": role_id})

    assert response.status_code == 403
    assert response.json()["code"] == "escalation"


async def test_a_role_beyond_your_own_permissions_is_refused(
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
    family = (await roles(keeper, ids["home"]))["family"]

    refused = await keeper.post(f"/homes/{ids['home']}/invitations", json={"role_id": family})
    allowed = await keeper.post(f"/homes/{ids['home']}/invitations", json={"role_id": str(doorkeeper.id)})

    assert refused.status_code == 403
    assert refused.json()["code"] == "escalation"
    assert refused.json()["params"]["permissions"] == [
        "changes.apply",
        "devices.control",
        "entities.edit",
        "tasks.complete",
        "tasks.view",
    ]
    assert allowed.status_code == 201


async def invite_role(api: httpx.AsyncClient, home_id: str, role_id: str, **body: Any) -> str:
    created = await ok(await api.post(f"/homes/{home_id}/invitations", json={"role_id": role_id, **body}), 201)
    return str(created["url"]).removeprefix(f"{PUBLIC_URL}/invite/")


async def test_an_invitation_whose_inviter_lost_access_gives_nothing(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    token = await invite(admin, ids["home"], "family")
    [anna] = [m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if m["person"]["username"] == "anna"]
    await ok(await api.delete(f"/homes/{ids['home']}/grants/{anna['grants'][0]['id']}"), 204)

    response = await new_client().post(
        "/invitations:accept-new-account",
        json={"token": token, "username": "maria", "display_name": "Maria", "password": CHOSEN, "locale": "en"},
    )

    assert response.json()["code"] == "inviter_lost_access"


async def test_a_place_of_another_home_cannot_be_a_scope(api: httpx.AsyncClient) -> None:
    flat = await make_home(api, "Flat")
    dacha = await make_home(api, "Dacha")
    role_id = (await roles(api, flat["home"]))["family"]

    response = await api.post(
        f"/homes/{flat['home']}/invitations", json={"role_id": role_id, "scope_entity_id": dacha["kitchen"]}
    )

    assert response.status_code == 400
    assert response.json()["params"] == {"field": "scope_entity_id"}


# Members


async def test_the_members_list_shows_each_account_with_its_grants(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    await join(new_client, await invite(api, ids["home"], "contractor", scope_entity_id=ids["kitchen"]), "ivan")

    members = await ok(await api.get(f"/homes/{ids['home']}/members"))

    assert [(m["person"]["username"], m["you"], [g["role"]["preset"] for g in m["grants"]]) for m in members] == [
        ("owner", True, ["owner"]),
        ("ivan", False, ["contractor"]),
    ]
    assert members[1]["grants"][0]["scope"]["names"] == ["Country house", "House", "Kitchen"]
    assert members[0]["grants"][0]["granted_by"] is None


async def test_only_those_who_manage_people_see_the_list(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")

    assert (await maria.get(f"/homes/{ids['home']}/members")).status_code == 403
    assert (await new_client().get(f"/homes/{ids['home']}/members")).status_code == 401


async def test_a_stranger_does_not_learn_the_home_exists(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    other = await make_home(api, "Other")
    stranger = await member(api, new_client, other["home"], "admin", "stranger")

    response = await stranger.get(f"/homes/{ids['home']}/roles")

    assert response.json()["code"] == "home_not_found"


async def test_changing_a_members_role_and_place(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    [_, m] = await ok(await api.get(f"/homes/{ids['home']}/members"))
    contractor = (await roles(api, ids["home"]))["contractor"]

    await ok(
        await api.patch(
            f"/homes/{ids['home']}/grants/{m['grants'][0]['id']}",
            json={"role_id": contractor, "scope_entity_id": ids["kitchen"]},
        ),
        204,
    )

    [_, changed] = await ok(await api.get(f"/homes/{ids['home']}/members"))
    assert changed["grants"][0]["role"]["preset"] == "contractor"
    assert changed["grants"][0]["scope"]["id"] == ids["kitchen"]
    # The tree's top is no longer theirs.
    assert (await maria.get(f"/homes/{ids['home']}/entities")).status_code == 403
    assert (await event_types(container))[-1] == "grant.changed"


async def test_changing_a_role_needs_a_recent_sign_in(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    await member(api, new_client, ids["home"], "family", "maria")
    [_, m] = await ok(await api.get(f"/homes/{ids['home']}/members"))
    await age_sign_ins(container)

    response = await api.patch(f"/homes/{ids['home']}/grants/{m['grants'][0]['id']}", json={"expires_at": None})

    assert response.status_code == 403
    assert response.json()["code"] == "recent_sign_in_required"


async def test_an_owners_grant_is_not_changed(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    await member(api, new_client, ids["home"], "owner", "second")
    [theirs] = [m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if not m["you"]]
    family = (await roles(api, ids["home"]))["family"]

    response = await api.patch(f"/homes/{ids['home']}/grants/{theirs['grants'][0]['id']}", json={"role_id": family})

    assert (response.status_code, response.json()["code"]) == (409, "owner_grant")


async def test_nobody_changes_their_own_access(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna", grant_expires_at=later(days=2))
    [mine] = [m for m in await ok(await admin.get(f"/homes/{ids['home']}/members")) if m["you"]]

    response = await admin.patch(f"/homes/{ids['home']}/grants/{mine['grants'][0]['id']}", json={"expires_at": None})

    assert (response.status_code, response.json()["code"]) == (403, "own_grant")


async def test_revoking_a_members_access(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    [_, m] = await ok(await api.get(f"/homes/{ids['home']}/members"))

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{m['grants'][0]['id']}"), 204)

    assert await home_names(maria) == []
    assert (await maria.get(f"/homes/{ids['home']}")).status_code == 404


async def test_a_member_leaves_a_home(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")

    await ok(await maria.post(f"/homes/{ids['home']}:leave"), 204)

    assert await home_names(maria) == []


async def test_the_last_owner_cannot_leave_or_be_removed(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    [me] = await ok(await api.get(f"/homes/{ids['home']}/members"))

    leaving = await api.post(f"/homes/{ids['home']}:leave")
    revoking = await api.delete(f"/homes/{ids['home']}/grants/{me['grants'][0]['id']}")

    assert (leaving.status_code, leaving.json()["code"]) == (409, "last_owner")
    assert revoking.json()["code"] == "last_owner"
    assert await home_names(api) == ["Country house"]


async def test_an_owner_removes_another_owner(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    second = await member(api, new_client, ids["home"], "owner", "second")
    members = await ok(await api.get(f"/homes/{ids['home']}/members"))
    [theirs] = [m for m in members if m["person"]["username"] == "second"]

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{theirs['grants'][0]['id']}"), 204)

    assert await home_names(second) == []


async def test_an_admin_cannot_remove_an_owner(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    members = await ok(await admin.get(f"/homes/{ids['home']}/members"))
    [owner] = [m for m in members if m["person"]["username"] == "owner"]

    response = await admin.delete(f"/homes/{ids['home']}/grants/{owner['grants'][0]['id']}")

    assert response.json()["code"] == "escalation"


async def test_removing_an_owner_needs_a_recent_sign_in(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    await member(api, new_client, ids["home"], "owner", "second")
    [theirs] = [m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if not m["you"]]
    await age_sign_ins(container)

    response = await api.delete(f"/homes/{ids['home']}/grants/{theirs['grants'][0]['id']}")

    assert response.json()["code"] == "recent_sign_in_required"


# Ownership


async def test_transferring_ownership(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    token = await invite(api, ids["home"], "owner", leave_when_accepted=True)
    preview = await ok(await new_client().post("/invitations:preview", json={"token": token}))

    heir = await join(new_client, token, "heir")

    assert preview["leave_when_accepted"] is True
    assert await home_names(api) == []
    assert (await ok(await heir.get(f"/homes/{ids['home']}")))["access"]["owner"] is True
    [only] = await ok(await heir.get(f"/homes/{ids['home']}/members"))
    assert only["person"]["username"] == "heir"
    assert (await event_types(container))[-2:] == ["grant.revoked", "account.signed_in"]


async def test_inviting_an_owner_needs_a_recent_sign_in(api: httpx.AsyncClient, container: DishkaContainer) -> None:
    ids = await make_home(api)
    owner = (await roles(api, ids["home"]))["owner"]
    await age_sign_ins(container)

    response = await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": owner, "leave_when_accepted": True})

    assert response.json()["code"] == "recent_sign_in_required"


async def test_only_an_owner_invitation_transfers_ownership(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    admin = (await roles(api, ids["home"]))["admin"]

    response = await api.post(f"/homes/{ids['home']}/invitations", json={"role_id": admin, "leave_when_accepted": True})

    assert response.json()["params"] == {"field": "leave_when_accepted"}


# Guest links


async def guest_link(api: httpx.AsyncClient, home_id: str, **body: Any) -> str:
    guest = (await roles(api, home_id))["guest"]
    created = await ok(
        await api.post(f"/homes/{home_id}/guest-links", json={"name": "Weekend", "role_id": guest, **body}), 201
    )
    return str(created["url"]).removeprefix(f"{PUBLIC_URL}/guest/")


async def test_a_guest_link_opens_a_guest_view_of_guest_visible_things(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    bed = {"kind": "item", "name": "Bed", "parent_id": ids["guest_room"]}
    await ok(await api.post(f"/homes/{ids['home']}/entities", json=bed), 201)
    token = await guest_link(api, ids["home"])
    guest = new_client()

    opened = await ok(await guest.post("/guest-sessions", json={"token": token}))

    assert opened["home"] == {"id": ids["home"], "name": "Country house"}
    assert opened["name"] == "Weekend"
    assert opened["scope"] is None
    assert await ok(await guest.get("/guest")) == opened
    top = await ok(await guest.get(f"/homes/{ids['home']}/entities"))
    inside = await ok(await guest.get(f"/homes/{ids['home']}/entities", params={"parent_id": ids["house"]}))
    assert [e["name"] for e in top] == ["Country house"]
    # Only the way to the towels: no kitchen, no study.
    assert [e["name"] for e in inside] == ["Guest room"]
    # Counts leave out what a guest does not see: the bed beside the towels.
    assert (top[0]["children"], inside[0]["children"]) == (1, 1)
    assert (await guest.get(f"/entities/{ids['kitchen']}")).status_code == 404


async def test_a_guest_link_lasts_three_days_and_can_be_reused(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])

    first = await ok(await new_client().post("/guest-sessions", json={"token": token}))
    second = await ok(await new_client().post("/guest-sessions", json={"token": token}))

    [link] = await ok(await api.get(f"/homes/{ids['home']}/guest-links"))
    assert first["expires_at"] == second["expires_at"] == link["expires_at"]
    lasts = datetime.fromisoformat(link["expires_at"]) - datetime.fromisoformat(link["created_at"])
    assert lasts == timedelta(days=3)
    assert link["last_used_at"] is not None


async def test_a_guest_cannot_reach_the_account_or_change_anything(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": await guest_link(api, ids["home"])}))

    me = await guest.get("/me")
    new_home = await guest.post("/homes", json={"name": "Mine", "timezone": "UTC", "locale": "en"})
    edit = await guest.post(
        f"/homes/{ids['home']}/entities", json={"kind": "item", "name": "x", "parent_id": ids["guest_room"]}
    )
    members = await guest.get(f"/homes/{ids['home']}/members")

    assert (me.status_code, me.json()["code"]) == (401, "unauthenticated")
    assert (new_home.status_code, new_home.json()["code"]) == (403, "account_required")
    assert edit.status_code == 403
    assert members.status_code == 401


async def test_revoking_a_guest_link_ends_its_visits_at_once(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": token}))
    [link] = await ok(await api.get(f"/homes/{ids['home']}/guest-links"))

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{link['grant_id']}"), 204)

    assert (await guest.get("/guest")).status_code == 401
    reopened = await new_client().post("/guest-sessions", json={"token": token})
    assert reopened.json()["code"] == "guest_link_ended"
    assert await ok(await api.get(f"/homes/{ids['home']}/guest-links")) == []
    assert (await event_types(container))[-3:] == ["guest_link.created", "guest_link.opened", "guest_link.revoked"]


async def test_an_expired_guest_link_ends_the_visit(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": await guest_link(api, ids["home"])}))
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(
            update(GrantDB)
            .where(GrantDB.principal_type == "link")
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert (await guest.get("/guest")).status_code == 401


async def test_a_guest_link_scoped_to_a_place_starts_there(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    guest = new_client()

    opened = await ok(
        await guest.post(
            "/guest-sessions", json={"token": await guest_link(api, ids["home"], scope_entity_id=ids["guest_room"])}
        )
    )

    assert opened["scope"] == {"id": ids["guest_room"], "names": ["Country house", "House", "Guest room"]}
    assert (await guest.get(f"/homes/{ids['home']}/entities")).status_code == 403
    inside = await ok(await guest.get(f"/homes/{ids['home']}/entities", params={"parent_id": ids["guest_room"]}))
    assert [e["name"] for e in inside] == ["Towels"]


async def test_a_guest_link_gives_only_a_role_with_guest_view(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    family = (await roles(api, ids["home"]))["family"]

    response = await api.post(f"/homes/{ids['home']}/guest-links", json={"name": "Kids", "role_id": family})

    assert response.json()["params"] == {"field": "role_id"}


async def test_an_unknown_guest_link_is_not_found(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.post("/guest-sessions", json={"token": "nothing"})

    assert (response.status_code, response.json()["code"]) == (404, "guest_link_not_found")


async def test_a_guest_session_is_not_an_account_session(api: httpx.AsyncClient) -> None:
    response = await api.get("/guest")

    assert response.status_code == 401


# Between homes


async def strangers_home(api: httpx.AsyncClient, new_client: NewClient, home_id: str) -> tuple[httpx.AsyncClient, str]:
    """Another account and a home of its own, where the owner of the tests holds nothing."""
    bob = await member(api, new_client, home_id, "family", "bob")
    other = await make_home(bob, "Bob's flat")
    return bob, other["home"]


async def test_ids_of_another_home_reach_nothing(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    bob, bobs_home = await strangers_home(api, new_client, ids["home"])
    await invite(bob, bobs_home, "guest")
    [bobs_member] = await ok(await bob.get(f"/homes/{bobs_home}/members"))
    bobs_grant = bobs_member["grants"][0]["id"]
    [bobs_invitation] = await ok(await bob.get(f"/homes/{bobs_home}/invitations"))
    bobs_family = (await roles(bob, bobs_home))["family"]
    [_, mine] = await ok(await api.get(f"/homes/{ids['home']}/members"))
    home = ids["home"]

    responses = [
        await api.patch(f"/homes/{home}/grants/{bobs_grant}", json={"expires_at": None}),
        await api.delete(f"/homes/{home}/grants/{bobs_grant}"),
        await api.delete(f"/homes/{home}/invitations/{bobs_invitation['id']}"),
        await api.post(f"/homes/{home}/invitations", json={"role_id": bobs_family}),
        await api.patch(f"/homes/{home}/grants/{mine['grants'][0]['id']}", json={"role_id": bobs_family}),
    ]

    assert [(r.status_code, r.json()["code"]) for r in responses] == [
        (404, "grant_not_found"),
        (404, "grant_not_found"),
        (404, "invitation_not_found"),
        (404, "role_not_found"),
        (404, "role_not_found"),
    ]
    assert len(await ok(await bob.get(f"/homes/{bobs_home}/invitations"))) == 1
    assert await home_names(bob) == ["Bob's flat", "Country house"]


# Who may revoke an invitation


async def test_revoking_invitations_follows_who_could_have_made_them(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    await invite(api, ids["home"], "contractor")
    [pending] = await ok(await api.get(f"/homes/{ids['home']}/invitations"))
    url = f"/homes/{ids['home']}/invitations/{pending['id']}"

    by_family = await maria.delete(url)
    by_admin = await admin.delete(url)
    again = await api.delete(url)

    assert (by_family.status_code, by_family.json()["code"]) == (403, "permission_denied")
    assert by_admin.status_code == 204
    assert (again.status_code, again.json()["code"]) == (409, "invitation_revoked")


async def test_an_accepted_invitation_cannot_be_revoked(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    await join(new_client, await invite(api, ids["home"], "family"), "maria")
    async with (await uow_of(container)).query() as tx:
        invitation_id = await tx.session.scalar(select(InvitationDB.id))

    response = await api.delete(f"/homes/{ids['home']}/invitations/{invitation_id}")

    assert (response.status_code, response.json()["code"]) == (409, "invitation_used")


# Access over one place


async def doorkeeper_over_the_house(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer, ids: dict[str, str]
) -> tuple[httpx.AsyncClient, Role]:
    """Someone who manages people, and sees things, only in the house."""
    keeper_role = Role(
        home_id=UUID(ids["home"]),
        preset=None,
        name="Doorkeeper",
        all_permissions=False,
        permissions=frozenset({"members.manage", "entities.view"}),
    )
    async with (await uow_of(container)).transaction() as tx:
        await tx.roles.add_all([keeper_role])
    token = await invite_role(api, ids["home"], str(keeper_role.id), scope_entity_id=ids["house"])
    return await join(new_client, token, "keeper"), keeper_role


async def test_access_over_a_place_gives_access_only_inside_it(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    keeper, keeper_role = await doorkeeper_over_the_house(api, new_client, container, ids)
    body = {"role_id": str(keeper_role.id)}
    url = f"/homes/{ids['home']}/invitations"

    inside = await keeper.post(url, json={**body, "scope_entity_id": ids["kitchen"]})
    whole_home = await keeper.post(url, json=body)
    members = await keeper.get(f"/homes/{ids['home']}/members")

    assert inside.status_code == 201
    assert (whole_home.status_code, whole_home.json()["code"]) == (403, "permission_denied")
    assert (members.status_code, members.json()["code"]) == (403, "permission_denied")


# Changing a grant


async def maria_as(api: httpx.AsyncClient, new_client: NewClient, home_id: str, preset: str, **body: Any) -> str:
    """Maria joins with the role; the id of her grant."""
    await member(api, new_client, home_id, preset, "maria", **body)
    [m] = [m for m in await ok(await api.get(f"/homes/{home_id}/members")) if m["person"]["username"] == "maria"]
    return str(m["grants"][0]["id"])


async def grant_of(api: httpx.AsyncClient, home_id: str, grant_id: str) -> dict[str, Any]:
    grants = [g for m in await ok(await api.get(f"/homes/{home_id}/members")) for g in m["grants"]]
    [grant] = [g for g in grants if g["id"] == grant_id]
    return dict(grant)


async def test_a_patch_changes_only_what_it_names(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    grant_id = await maria_as(api, new_client, ids["home"], "family", scope_entity_id=ids["kitchen"])
    url = f"/homes/{ids['home']}/grants/{grant_id}"
    contractor = (await roles(api, ids["home"]))["contractor"]

    await ok(await api.patch(url, json={"role_id": contractor}), 204)
    kept = await grant_of(api, ids["home"], grant_id)
    await ok(await api.patch(url, json={"scope_entity_id": None}), 204)
    whole = await grant_of(api, ids["home"], grant_id)

    assert (kept["role"]["preset"], kept["scope"]["id"], kept["expires_at"]) == ("contractor", ids["kitchen"], None)
    assert (whole["role"]["preset"], whole["scope"]) == ("contractor", None)


async def test_a_role_that_must_end_gets_its_default_end(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    grant_id = await maria_as(api, new_client, ids["home"], "family")
    guest = (await roles(api, ids["home"]))["guest"]

    await ok(await api.patch(f"/homes/{ids['home']}/grants/{grant_id}", json={"role_id": guest}), 204)

    ends = datetime.fromisoformat((await grant_of(api, ids["home"], grant_id))["expires_at"])
    assert timedelta(days=3) - timedelta(minutes=1) < ends - datetime.now(UTC) <= timedelta(days=3)


async def test_the_end_of_a_role_that_must_end_cannot_be_cleared(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    grant_id = await maria_as(api, new_client, ids["home"], "guest")

    response = await api.patch(f"/homes/{ids['home']}/grants/{grant_id}", json={"expires_at": None})

    assert (response.status_code, response.json()["params"]) == (400, {"field": "expires_at"})


async def test_a_guest_links_grant_is_not_changed(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    await guest_link(api, ids["home"])
    [link] = await ok(await api.get(f"/homes/{ids['home']}/guest-links"))

    response = await api.patch(f"/homes/{ids['home']}/grants/{link['grant_id']}", json={"expires_at": later(days=1)})

    assert (response.status_code, response.json()["params"]) == (400, {"field": "grant"})


# Races


async def test_of_two_admins_demoting_each_other_one_wins(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    anna = await member(api, new_client, ids["home"], "admin", "anna")
    boris = await member(api, new_client, ids["home"], "admin", "boris")
    members = {
        m["person"]["username"]: m["grants"][0]["id"] for m in await ok(await api.get(f"/homes/{ids['home']}/members"))
    }
    family = {"role_id": (await roles(api, ids["home"]))["family"]}

    results = await asyncio.gather(
        anna.patch(f"/homes/{ids['home']}/grants/{members['boris']}", json=family),
        boris.patch(f"/homes/{ids['home']}/grants/{members['anna']}", json=family),
    )

    assert sorted(r.status_code for r in results) == [204, 403]


async def test_an_invitation_accepted_twice_at_once_gives_one_grant(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "guest", "maria")
    other_home_owner, other_home = await strangers_home(api, new_client, ids["home"])
    token = await invite(other_home_owner, other_home, "family")

    results = await asyncio.gather(
        maria.post("/invitations:accept", json={"token": token}),
        api.post("/invitations:accept", json={"token": token}),
    )

    assert sorted(r.status_code for r in results) == [200, 409]


# Leaving


async def test_an_owner_leaves_while_another_owner_stays(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    second = await member(api, new_client, ids["home"], "owner", "second")
    await age_sign_ins(container)

    too_old = await api.post(f"/homes/{ids['home']}:leave")
    await ok(await second.post("/me/reauthenticate", json={"password": CHOSEN}), 204)
    await ok(await second.post(f"/homes/{ids['home']}:leave"), 204)

    assert (too_old.status_code, too_old.json()["code"]) == (403, "recent_sign_in_required")
    assert await home_names(second) == []
    assert await home_names(api) == ["Country house"]


async def test_leaving_gives_up_every_grant_in_the_home(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    maria = await member(api, new_client, ids["home"], "contractor", "maria", scope_entity_id=ids["kitchen"])
    await ok(await maria.post("/invitations:accept", json={"token": await invite(api, ids["home"], "guest")}))

    await ok(await maria.post(f"/homes/{ids['home']}:leave"), 204)

    assert await home_names(maria) == []
    assert [m["person"]["username"] for m in await ok(await api.get(f"/homes/{ids['home']}/members"))] == ["owner"]


# Guest links: limits and their makers


async def test_guessing_guest_link_tokens_makes_the_address_wait(anonymous: httpx.AsyncClient) -> None:
    statuses = [(await anonymous.post("/guest-sessions", json={"token": f"guess-{n}"})).status_code for n in range(6)]

    assert statuses == [404, 404, 404, 404, 404, 429]


async def test_a_household_opens_a_guest_link_many_times(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])

    statuses = [(await new_client().post("/guest-sessions", json={"token": token})).status_code for _ in range(7)]

    assert statuses == [200] * 7


async def test_reopening_a_guest_link_keeps_the_browsers_session(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])
    guest = new_client()

    for _ in range(3):
        await ok(await guest.post("/guest-sessions", json={"token": token}))

    async with (await uow_of(container)).query() as tx:
        guest_sessions = await tx.session.scalar(
            select(func.count()).select_from(SessionDB).where(SessionDB.grant_id.is_not(None))
        )
    assert guest_sessions == 1


async def test_a_guest_link_keeps_a_bounded_number_of_visits_open(
    api: httpx.AsyncClient, new_client: NewClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guest_links, "GUEST_SESSIONS_MAX", 2)
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])
    first, second, third = new_client(), new_client(), new_client()

    for guest in (first, second, third):
        await ok(await guest.post("/guest-sessions", json={"token": token}))

    assert [(await guest.get("/guest")).status_code for guest in (first, second, third)] == [401, 200, 200]


async def test_a_guest_link_lasts_ninety_days_at_most(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    guest = (await roles(api, ids["home"]))["guest"]

    response = await api.post(
        f"/homes/{ids['home']}/guest-links",
        json={"name": "Summer", "role_id": guest, "expires_at": later(days=91)},
    )

    assert (response.status_code, response.json()["params"]) == (400, {"field": "expires_at", "max_days": 90})


async def test_a_guest_link_ends_when_its_maker_loses_access(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    admin = await member(api, new_client, ids["home"], "admin", "anna")
    token = await guest_link(admin, ids["home"])
    visitor = new_client()
    await ok(await visitor.post("/guest-sessions", json={"token": token}))
    [anna] = [m for m in await ok(await api.get(f"/homes/{ids['home']}/members")) if m["person"]["username"] == "anna"]

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{anna['grants'][0]['id']}"), 204)

    assert (await visitor.get("/guest")).status_code == 401
    assert await ok(await api.get(f"/homes/{ids['home']}/guest-links")) == []
    assert (await last_events(container, 1))[0][2]["reason"] == "giver_lost_access"


# The journal


async def last_events(container: DishkaContainer, count: int) -> list[tuple[str, str, dict[str, Any]]]:
    """The last events, oldest first: their type, actor kind and payload with ids as "uuid"."""
    async with (await uow_of(container)).query() as tx:
        rows = list(await tx.session.scalars(select(JournalEventDB).order_by(JournalEventDB.seq.desc()).limit(count)))
    return [(row.type, row.actor["kind"], shape(row.payload)) for row in reversed(rows)]


async def test_a_transfer_is_journalled(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)

    await join(new_client, await invite(api, ids["home"], "owner", leave_when_accepted=True), "heir")

    events = await last_events(container, 5)
    owner = {"principal_type": "user", "role": "owner", "scope_entity_id": None, "expires_at": None}
    assert events[1:4] == [
        ("invitation.accepted", "user", {"invitation_id": "uuid", "user_id": "uuid", "grant_id": "uuid"}),
        (
            "grant.created",
            "user",
            {**owner, "grant_id": "uuid", "principal_id": "uuid", "role_id": "uuid", "invitation_id": "uuid"},
        ),
        (
            "grant.revoked",
            "user",
            {**owner, "grant_id": "uuid", "principal_id": "uuid", "role_id": "uuid", "reason": "transferred"},
        ),
    ]


async def test_a_new_home_journals_its_owner_grant_like_any_other(
    api: httpx.AsyncClient, container: DishkaContainer
) -> None:
    await make_home(api)

    [created] = [e for e in await last_events(container, 20) if e[0] == "grant.created"]

    assert created[2] == {
        "grant_id": "uuid",
        "principal_type": "user",
        "principal_id": "uuid",
        "role_id": "uuid",
        "role": "owner",
        "scope_entity_id": None,
        "expires_at": None,
    }


async def test_revoking_a_guest_link_is_journalled_with_its_visits(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])
    await ok(await new_client().post("/guest-sessions", json={"token": token}))
    [link] = await ok(await api.get(f"/homes/{ids['home']}/guest-links"))

    await ok(await api.delete(f"/homes/{ids['home']}/grants/{link['grant_id']}"), 204)

    assert await last_events(container, 1) == [
        (
            "guest_link.revoked",
            "user",
            {"link_id": "uuid", "grant_id": "uuid", "sessions_ended": 1, "reason": "revoked"},
        )
    ]


# What a member without private access, and a guest, learn of places


async def test_history_leaves_out_private_places(api: httpx.AsyncClient, new_client: NewClient) -> None:
    ids = await make_home(api)
    safe = await ok(
        await api.post(
            f"/homes/{ids['home']}/entities",
            json={"kind": "container", "name": "Safe", "parent_id": ids["study"], "privacy": "normal"},
        ),
        201,
    )
    ring = await ok(
        await api.post(
            f"/homes/{ids['home']}/entities", json={"kind": "item", "name": "Ring", "parent_id": safe["id"]}
        ),
        201,
    )
    await ok(await api.post(f"/entities/{ring['id']}:move", json={"parent_id": ids["kitchen"], "version": 1}))
    maria = await member(api, new_client, ids["home"], "family", "maria")

    history = await ok(await maria.get(f"/entities/{ring['id']}/history"))

    assert [(e["type"], e["payload"].get("parent"), e["payload"].get("from")) for e in history] == [
        ("entity.moved", None, None),
        ("entity.created", None, None),
    ]
    assert history[0]["payload"]["to"]["name"] == "Kitchen"


async def test_a_guest_sees_no_history_and_only_the_names_of_places_on_the_way(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    room = await ok(await api.get(f"/entities/{ids['guest_room']}"))
    await ok(
        await api.patch(f"/entities/{ids['guest_room']}", json={"version": room["version"], "aliases": ["spare room"]})
    )
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": await guest_link(api, ids["home"])}))

    history = await guest.get(f"/entities/{ids['towels']}/history")
    seen = await ok(await guest.get(f"/entities/{ids['guest_room']}"))

    assert (history.status_code, history.json()["code"]) == (403, "permission_denied")
    assert (seen["name"], seen["aliases"]) == ("Guest room", [])


async def test_history_judges_each_place_by_the_readers_access_there(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    shed = await ok(
        await api.post(
            f"/homes/{ids['home']}/entities", json={"kind": "space", "name": "Shed", "parent_id": ids["house"]}
        ),
        201,
    )
    rake = await ok(
        await api.post(
            f"/homes/{ids['home']}/entities", json={"kind": "item", "name": "Rake", "parent_id": shed["id"]}
        ),
        201,
    )
    await ok(await api.post(f"/entities/{rake['id']}:move", json={"parent_id": ids["kitchen"], "version": 1}))
    # An admin, so private places would show, but only over the kitchen.
    admin = await member(api, new_client, ids["home"], "admin", "anna", scope_entity_id=ids["kitchen"])

    history = await ok(await admin.get(f"/entities/{rake['id']}/history"))

    assert [(e["type"], e["payload"].get("parent"), e["payload"].get("from")) for e in history] == [
        ("entity.moved", None, None),
        ("entity.created", None, None),
    ]
    assert history[0]["payload"]["to"]["name"] == "Kitchen"


async def test_opening_an_ended_guest_link_does_not_count_as_guessing(
    api: httpx.AsyncClient, new_client: NewClient
) -> None:
    ids = await make_home(api)
    token = await guest_link(api, ids["home"])
    [link] = await ok(await api.get(f"/homes/{ids['home']}/guest-links"))
    await ok(await api.delete(f"/homes/{ids['home']}/grants/{link['grant_id']}"), 204)
    guest = new_client()

    answers = [(await guest.post("/guest-sessions", json={"token": token})).json()["code"] for _ in range(6)]

    assert answers == ["guest_link_ended"] * 6


async def demote(api: httpx.AsyncClient, home_id: str, anna: httpx.AsyncClient) -> None:
    [m] = [m for m in await ok(await api.get(f"/homes/{home_id}/members")) if m["person"]["username"] == "anna"]
    family = (await roles(api, home_id))["family"]
    await ok(await api.patch(f"/homes/{home_id}/grants/{m['grants'][0]['id']}", json={"role_id": family}), 204)


async def leave(api: httpx.AsyncClient, home_id: str, anna: httpx.AsyncClient) -> None:
    await ok(await anna.post(f"/homes/{home_id}:leave"), 204)


@pytest.mark.parametrize("lose_access", [demote, leave], ids=["demoted", "left"])
async def test_a_guest_link_ends_when_its_maker_is_demoted_or_leaves(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer, lose_access: Any
) -> None:
    ids = await make_home(api)
    anna = await member(api, new_client, ids["home"], "admin", "anna")
    visitor = new_client()
    await ok(await visitor.post("/guest-sessions", json={"token": await guest_link(anna, ids["home"])}))

    await lose_access(api, ids["home"], anna)

    assert (await visitor.get("/guest")).status_code == 401
    assert [e[2]["reason"] for e in await last_events(container, 5) if e[0] == "guest_link.revoked"] == [
        "giver_lost_access"
    ]


async def test_handing_the_home_over_ends_the_old_owners_guest_links(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    visitor = new_client()
    await ok(await visitor.post("/guest-sessions", json={"token": await guest_link(api, ids["home"])}))

    await join(new_client, await invite(api, ids["home"], "owner", leave_when_accepted=True), "heir")

    assert (await visitor.get("/guest")).status_code == 401
    assert [e[2]["reason"] for e in await last_events(container, 6) if e[0] == "guest_link.revoked"] == [
        "giver_lost_access"
    ]

"""Who sees a file, and who may change it (docs/design/documents.md, 6)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import pytest
from servicewright import BootstrapContext, HealthRegistry, ServiceContext
from servicewright.adapters.dishka import DishkaContainer

from penaria.apps.api.container import build_container
from penaria.apps.api.entrypoint import build_http
from penaria.apps.api.settings import Settings
from penaria.features.support.identity.domain.models import Role
from tests import images
from tests.integration.apps.api.test_devices import add_device, bearer
from tests.integration.apps.api.test_people import guest_link, make_home, member, ok, roles
from tests.integration.files.conftest import Run
from tests.integration.files.helpers import detail, listed, upload
from tests.integration.helpers import NewClient, uow_of

pytestmark = pytest.mark.integration


@dataclass
class Shelf:
    ids: dict[str, str]
    # The files' ids, by name.
    files: dict[str, str]


@pytest.fixture
async def shelf(api: httpx.AsyncClient, worker: Run) -> Shelf:
    """The towels meant for guests have a photo, a manual, a receipt and a private photo; the private
    study has a note."""
    ids = await make_home(api)
    files = {}
    for entity, name, data, kind in (
        ("towels", "photo.jpg", images.jpeg(), "photo"),
        ("towels", "manual.pdf", images.pdf(), "manual"),
        ("towels", "receipt.pdf", images.pdf(), "receipt"),
        ("towels", "hidden.jpg", images.jpeg(), "photo"),
        ("study", "note.txt", b"the safe's code is elsewhere", "other"),
    ):
        files[name] = (await upload(api, ids[entity], name, data, kind=kind))["id"]
    await ok(await api.patch(f"/files/{files['hidden.jpg']}", json={"visibility": "private"}))
    await worker()
    return Shelf(ids=ids, files=files)


async def reachable(client: httpx.AsyncClient, shelf: Shelf) -> dict[str, int]:
    """The status of each file's content, which must agree with its description."""
    statuses = {}
    for name, file_id in shelf.files.items():
        content = await client.get(f"/files/{file_id}/content")
        described = await client.get(f"/files/{file_id}")
        assert content.status_code == described.status_code, name
        statuses[name] = content.status_code
    return statuses


async def add_kinds(client: httpx.AsyncClient, entity_id: str) -> list[str]:
    kinds: list[str] = (await ok(await client.get(f"/entities/{entity_id}/files")))["add_kinds"]
    return kinds


async def test_new_photos_are_for_guests_and_documents_for_members(api: httpx.AsyncClient, shelf: Shelf) -> None:
    visibility = {name: (await detail(api, file_id))["visibility"] for name, file_id in shelf.files.items()}

    assert visibility == {
        "photo.jpg": "guests",
        "manual.pdf": "normal",
        "receipt.pdf": "normal",
        "hidden.jpg": "private",
        "note.txt": "normal",
    }


async def test_a_family_member_sees_receipts_but_nothing_private(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    maria = await member(api, new_client, shelf.ids["home"], "family", "maria")

    assert await reachable(maria, shelf) == {
        "photo.jpg": 200,
        "manual.pdf": 200,
        "receipt.pdf": 200,
        "hidden.jpg": 404,
        "note.txt": 404,
    }
    assert await listed(maria, shelf.ids["towels"]) == ["photo.jpg", "manual.pdf", "receipt.pdf"]
    assert await add_kinds(maria, shelf.ids["towels"]) == ["photo", "receipt", "warranty", "manual", "other"]
    study = await maria.get(f"/entities/{shelf.ids['study']}/files")
    assert (study.status_code, study.json()["code"]) == (404, "entity_not_found")


async def test_a_contractor_sees_no_receipts_and_changes_nothing(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    worker_man = await member(api, new_client, shelf.ids["home"], "contractor", "electrician")
    manual = shelf.files["manual.pdf"]

    assert await reachable(worker_man, shelf) == {
        "photo.jpg": 200,
        "manual.pdf": 200,
        "receipt.pdf": 404,
        "hidden.jpg": 404,
        "note.txt": 404,
    }
    towels = await ok(await worker_man.get(f"/entities/{shelf.ids['towels']}/files"))
    assert [f["name"] for f in towels["files"]] == ["photo.jpg", "manual.pdf"]
    assert towels["add_kinds"] == []
    assert [(f["can_edit"], f["can_detach"], f["can_set_cover"]) for f in towels["files"]] == [
        (False, False, False),
        (False, False, False),
    ]
    refused = [
        await worker_man.post(
            f"/entities/{shelf.ids['towels']}/files", params={"kind": "other"}, files={"file": ("a", b"x")}
        ),
        await worker_man.patch(f"/files/{manual}", json={"name": "mine.pdf"}),
        await worker_man.delete(f"/files/{manual}"),
        await worker_man.delete(f"/entities/{shelf.ids['towels']}/files/{manual}"),
        await worker_man.put(f"/entities/{shelf.ids['kitchen']}/files/{manual}"),
        await worker_man.put(f"/entities/{shelf.ids['towels']}/cover", json={"file_id": shelf.files["photo.jpg"]}),
    ]
    assert [(r.status_code, r.json()["code"]) for r in refused] == [(403, "permission_denied")] * 6


async def test_a_guest_sees_only_what_is_for_guests_on_what_is_for_guests(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": await guest_link(api, shelf.ids["home"])}))

    assert await reachable(guest, shelf) == {
        "photo.jpg": 200,
        "manual.pdf": 404,
        "receipt.pdf": 404,
        "hidden.jpg": 404,
        "note.txt": 404,
    }
    assert await listed(guest, shelf.ids["towels"]) == ["photo.jpg"]
    # A place on the way to the towels shows its name only; a place with nothing for guests, nothing.
    on_the_way = await ok(await guest.get(f"/entities/{shelf.ids['guest_room']}/files"))
    assert on_the_way == {"files": [], "add_kinds": []}
    assert (await guest.get(f"/entities/{shelf.ids['kitchen']}/files")).status_code == 404
    photo = await detail(guest, shelf.files["photo.jpg"])
    assert [place["names"][-1] for place in photo["entities"]] == ["Towels"]


async def test_a_document_is_shown_to_guests_only_when_someone_says_so(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": await guest_link(api, shelf.ids["home"])}))

    for name in ("manual.pdf", "receipt.pdf"):
        await ok(await api.patch(f"/files/{shelf.files[name]}", json={"visibility": "guests"}))

    # The receipt still needs the permission a guest does not have.
    assert await listed(guest, shelf.ids["towels"]) == ["photo.jpg", "manual.pdf"]


async def test_a_photo_that_becomes_a_document_stops_being_shown_to_guests(
    api: httpx.AsyncClient, shelf: Shelf
) -> None:
    changed = await ok(await api.patch(f"/files/{shelf.files['photo.jpg']}", json={"kind": "warranty"}))
    back = await ok(await api.patch(f"/files/{shelf.files['photo.jpg']}", json={"kind": "photo"}))

    assert (changed["kind"], changed["visibility"]) == ("warranty", "normal")
    # Never wider by itself.
    assert (back["kind"], back["visibility"]) == ("photo", "normal")


async def test_an_editor_without_the_permission_neither_adds_nor_makes_receipts(
    api: httpx.AsyncClient, new_client: NewClient, container: DishkaContainer, shelf: Shelf
) -> None:
    helper = Role(
        home_id=UUID(shelf.ids["home"]),
        preset=None,
        name="Helper",
        all_permissions=False,
        permissions=frozenset({"entities.view", "entities.edit"}),
    )
    async with (await uow_of(container)).transaction() as tx:
        await tx.roles.add_all([helper])
    invited = await ok(await api.post(f"/homes/{shelf.ids['home']}/invitations", json={"role_id": str(helper.id)}), 201)
    hired = new_client()
    await ok(
        await hired.post(
            "/invitations:accept-new-account",
            json={
                "token": invited["url"].rsplit("/", 1)[1],
                "username": "helper",
                "display_name": "Helper",
                "password": "a long family password",
                "locale": "en",
            },
        )
    )
    towels = shelf.ids["towels"]

    receipt = await upload(hired, towels, "bill.pdf", images.pdf(), kind="receipt", status=403)
    turned = await hired.patch(f"/files/{shelf.files['manual.pdf']}", json={"kind": "warranty"})
    secret = await hired.patch(f"/files/{shelf.files['manual.pdf']}", json={"visibility": "private"})

    assert await add_kinds(hired, towels) == ["photo", "manual", "other"]
    assert (receipt["code"], receipt["params"]) == ("permission_denied", {"permission": "documents.view_financial"})
    assert turned.json()["params"] == {"permission": "documents.view_financial"}
    assert secret.json()["params"] == {"permission": "entities.view_private"}


async def test_changing_a_file_takes_editing_every_place_that_holds_it(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    manual = shelf.files["manual.pdf"]
    await ok(await api.put(f"/entities/{shelf.ids['study']}/files/{manual}"))
    maria = await member(api, new_client, shelf.ids["home"], "family", "maria")

    seen = await detail(maria, manual)
    changed = await maria.patch(f"/files/{manual}", json={"name": "mine.pdf"})
    removed = await maria.delete(f"/files/{manual}")
    detached = await maria.delete(f"/entities/{shelf.ids['towels']}/files/{manual}")

    # The study is private, so it is not even named to her.
    assert [place["names"][-1] for place in seen["entities"]] == ["Towels"]
    assert seen["can_edit"] is False
    assert (changed.status_code, removed.status_code) == (403, 403)
    # Her own place she may still clear; the study keeps the file, and she no longer sees it.
    assert detached.status_code == 204
    assert (await maria.get(f"/files/{manual}")).status_code == 404
    assert [place["names"][-1] for place in (await detail(api, manual))["entities"]] == ["Study"]


async def test_attaching_takes_seeing_the_file(api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf) -> None:
    maria = await member(api, new_client, shelf.ids["home"], "family", "maria")

    refused = await maria.put(f"/entities/{shelf.ids['kitchen']}/files/{shelf.files['note.txt']}")

    assert (refused.status_code, refused.json()["code"]) == (404, "file_not_found")


async def test_a_file_stays_in_its_home(api: httpx.AsyncClient, shelf: Shelf) -> None:
    other = await make_home(api, "Flat")

    refused = await api.put(f"/entities/{other['kitchen']}/files/{shelf.files['manual.pdf']}")

    assert (refused.status_code, refused.json()["code"]) == (404, "file_not_found")


async def test_a_device_reads_and_adds_files_as_its_role_allows(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    mirror = await add_device(api, shelf.ids["home"], preset="contractor", name="Mirror")
    scanner = await add_device(api, shelf.ids["home"], preset="family", name="Scanner")
    read_only = bearer(new_client, mirror["token"])
    adding = bearer(new_client, scanner["token"])

    added = await upload(adding, shelf.ids["towels"], "scan.pdf", images.pdf(), kind="receipt")
    refused = await upload(read_only, shelf.ids["towels"], "a.pdf", images.pdf(), kind="manual", status=403)

    assert (await read_only.get(f"/files/{shelf.files['manual.pdf']}/content")).status_code == 200
    assert (await read_only.get(f"/files/{added['id']}")).status_code == 404
    assert refused["code"] == "permission_denied"


async def test_covers_show_only_what_the_reader_sees(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    ids = shelf.ids
    await ok(await api.put(f"/entities/{ids['towels']}/cover", json={"file_id": shelf.files["hidden.jpg"]}), 204)
    guest = new_client()
    await ok(await guest.post("/guest-sessions", json={"token": await guest_link(api, ids["home"])}))
    asked = {"entity_ids": [ids["towels"], ids["study"], ids["guest_room"], str(UUID(int=1))]}

    owners = await ok(await api.post("/covers:find", json=asked))
    guests = await ok(await guest.post("/covers:find", json=asked, headers={"Origin": "http://test"}))

    assert [(c["entity_id"], c["file"]["name"]) for c in owners] == [(ids["towels"], "hidden.jpg")]
    # The chosen cover is private: the guest gets the first photo meant for guests instead.
    assert [(c["entity_id"], c["file"]["name"]) for c in guests] == [(ids["towels"], "photo.jpg")]


async def test_the_family_role_of_a_new_home_sees_receipts(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)

    presets = await roles(api, ids["home"])
    listed_roles: list[dict[str, Any]] = await ok(await api.get(f"/homes/{ids['home']}/roles"))

    assert presets.keys() == {"owner", "admin", "family", "guest", "contractor"}
    holding = {role["preset"] for role in listed_roles if "documents.view_financial" in role["permissions"]}
    assert holding == {"family"}


async def test_access_over_one_place_reaches_only_the_files_inside_it(
    api: httpx.AsyncClient, new_client: NewClient, shelf: Shelf
) -> None:
    ids = shelf.ids
    kitchen_manual = (await upload(api, ids["kitchen"], "hob.pdf", images.pdf(), kind="manual"))["id"]
    electrician = await member(api, new_client, ids["home"], "contractor", "ivan", scope_entity_id=ids["kitchen"])
    tablet = await add_device(api, ids["home"], preset="family", name="Tablet", scope_entity_id=ids["kitchen"])
    device = bearer(new_client, tablet["token"])

    for client in (electrician, device):
        assert await listed(client, ids["kitchen"]) == ["hob.pdf"]
        assert (await client.get(f"/files/{kitchen_manual}")).status_code == 200
        assert (await client.get(f"/files/{shelf.files['manual.pdf']}")).status_code == 404
        elsewhere = await client.get(f"/entities/{ids['towels']}/files")
        assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "entity_not_found")
        found = await ok(await client.post("/covers:find", json={"entity_ids": [ids["towels"], ids["kitchen"]]}))
        assert found == []


@pytest.fixture
async def one_connection(
    settings: Settings, api: httpx.AsyncClient, new_client: NewClient
) -> AsyncIterator[httpx.AsyncClient]:
    """The owner's browser against a second api on the same data, whose pool holds a single connection."""
    pool = settings.database.pool.model_copy(update={"size": 1, "max_overflow": 0, "timeout": 2.0})
    small = settings.model_copy(update={"database": settings.database.model_copy(update={"pool": pool})})
    container = build_container(small)
    async with container.app_scope() as app_scope:
        bootstrap = BootstrapContext(settings=small, service_name="penaria-api", container=container)
        context = ServiceContext(bootstrap=bootstrap, app_scope=app_scope, health=HealthRegistry())
        app = await build_http(small).build_app(context)
        yield new_client(transport=httpx.ASGITransport(app=app), cookies=api.cookies)


async def test_every_read_of_files_gets_by_with_one_connection(
    api: httpx.AsyncClient, shelf: Shelf, one_connection: httpx.AsyncClient
) -> None:
    """Who may see what is asked with no connection of the reader's own held, so a page of thumbnails
    never waits for itself."""
    photo, towels = shelf.files["photo.jpg"], shelf.ids["towels"]
    await ok(await api.delete(f"/files/{shelf.files['manual.pdf']}"), 204)

    answers = [
        await one_connection.get(f"/entities/{towels}/files"),
        await one_connection.get(f"/files/{photo}"),
        await one_connection.get(f"/files/{photo}/content"),
        await one_connection.get(f"/files/{photo}/preview/320"),
        await one_connection.post("/covers:find", json={"entity_ids": [towels]}),
        await one_connection.get(f"/homes/{shelf.ids['home']}/files/trash"),
        await one_connection.post(f"/entities/{towels}/files", params={"kind": "other"}, files={"file": ("a", b"x")}),
    ]

    assert [answer.status_code for answer in answers] == [200] * 6 + [201]

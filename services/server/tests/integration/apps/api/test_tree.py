"""The home tree through the HTTP API, as the web app uses it."""

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


async def create(api: httpx.AsyncClient, url: str, body: dict[str, Any], expected: int = 201) -> dict[str, Any]:
    response = await api.post(url, json=body)
    assert response.status_code == expected, response.text
    data: dict[str, Any] = response.json()
    return data


async def make_home(api: httpx.AsyncClient) -> dict[str, str]:
    home = await create(api, "/homes", {"name": "Country house", "timezone": "Europe/Moscow", "locale": "ru"})
    home_id = home["id"]
    plot = await create(api, f"/homes/{home_id}/entities", {"kind": "property", "name": "Country house"})
    house = await create(
        api, f"/homes/{home_id}/entities", {"kind": "building", "name": "House", "parent_id": plot["id"]}
    )
    storage = await create(
        api, f"/homes/{home_id}/entities", {"kind": "space", "name": "Storage room", "parent_id": house["id"]}
    )
    kitchen = await create(
        api, f"/homes/{home_id}/entities", {"kind": "space", "name": "Kitchen", "parent_id": house["id"]}
    )
    return {
        "home": home_id,
        "plot": plot["id"],
        "house": house["id"],
        "storage": storage["id"],
        "kitchen": kitchen["id"],
    }


async def test_the_creator_owns_a_new_home(api: httpx.AsyncClient) -> None:
    home = await create(api, "/homes", {"name": "Flat", "timezone": "Europe/Moscow", "locale": "en"})

    assert home["access"]["owner"] is True
    listed = (await api.get("/homes")).json()
    assert [h["id"] for h in listed] == [home["id"]]


async def test_a_home_with_a_bad_time_zone_is_refused(api: httpx.AsyncClient) -> None:
    response = await api.post("/homes", json={"name": "Flat", "timezone": "Mars/Olympus", "locale": "en"})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_home"


async def test_an_entity_shows_its_path_and_its_parent_lists_it(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    vacuum = await create(
        api,
        f"/homes/{ids['home']}/entities",
        {"kind": "item", "name": "Vacuum cleaner", "parent_id": ids["storage"], "aliases": ["hoover"]},
    )

    assert [p["name"] for p in vacuum["path"]] == ["Country house", "House", "Storage room"]
    assert vacuum["freshness"] == "doubtful"
    assert vacuum["can_edit"] is True
    rooms = (await api.get(f"/homes/{ids['home']}/entities", params={"parent_id": ids["house"]})).json()
    assert [(r["name"], r["children"]) for r in rooms] == [("Kitchen", 0), ("Storage room", 1)]
    tops = (await api.get(f"/homes/{ids['home']}/entities")).json()
    assert [t["kind"] for t in tops] == ["property"]


async def test_a_thing_cannot_lie_directly_in_a_building(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)

    response = await api.post(
        f"/homes/{ids['home']}/entities", json={"kind": "item", "name": "Vacuum", "parent_id": ids["house"]}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "misplaced_entity"


async def test_moving_a_place_carries_its_contents(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    box = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "container", "name": "Box", "parent_id": ids["storage"]}
    )
    drill = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "item", "name": "Drill", "parent_id": box["id"]}
    )

    moved = await create(
        api, f"/entities/{box['id']}:move", {"parent_id": ids["kitchen"], "version": box["version"]}, expected=200
    )

    assert moved["freshness"] == "fresh"  # moving it means it was seen
    drill_now = (await api.get(f"/entities/{drill['id']}")).json()
    assert [p["name"] for p in drill_now["path"]] == ["Country house", "House", "Kitchen", "Box"]


async def test_a_place_cannot_move_into_itself(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    box = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "container", "name": "Box", "parent_id": ids["storage"]}
    )
    inner = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "container", "name": "Inner", "parent_id": box["id"]}
    )

    response = await api.post(f"/entities/{box['id']}:move", json={"parent_id": inner["id"], "version": 1})

    assert response.status_code == 400


async def test_an_edit_on_a_stale_version_is_refused(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    item = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "item", "name": "Plates", "parent_id": ids["kitchen"]}
    )

    first = await api.patch(f"/entities/{item['id']}", json={"version": 1, "quantity": "12"})
    second = await api.patch(f"/entities/{item['id']}", json={"version": 1, "name": "Bowls"})

    assert first.status_code == 200
    assert first.json()["quantity"] == "12"
    assert second.status_code == 409
    assert second.json()["code"] == "stale_version"


async def test_archived_things_leave_the_list_and_come_back(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    kettle = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "item", "name": "Old kettle", "parent_id": ids["kitchen"]}
    )
    listing = f"/homes/{ids['home']}/entities"

    archived = await create(
        api, f"/entities/{kettle['id']}:archive", {"reason": "discarded", "version": 1}, expected=200
    )
    assert archived["archive_reason"] == "discarded"
    assert (await api.get(listing, params={"parent_id": ids["kitchen"]})).json() == []
    with_archived = await api.get(listing, params={"parent_id": ids["kitchen"], "include_archived": True})
    assert [e["name"] for e in with_archived.json()] == ["Old kettle"]

    await create(api, f"/entities/{kettle['id']}:restore", {"version": archived["version"]}, expected=200)
    assert len((await api.get(listing, params={"parent_id": ids["kitchen"]})).json()) == 1


async def test_history_tells_what_happened_newest_first(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)
    vacuum = await create(
        api, f"/homes/{ids['home']}/entities", {"kind": "item", "name": "Vacuum", "parent_id": ids["storage"]}
    )
    await create(api, f"/entities/{vacuum['id']}:move", {"parent_id": ids["kitchen"], "version": 1}, expected=200)
    await create(api, f"/entities/{vacuum['id']}:verify", {}, expected=200)

    history = (await api.get(f"/entities/{vacuum['id']}/history")).json()

    assert [e["type"] for e in history] == ["entity.verified", "entity.moved", "entity.created"]
    assert history[1]["payload"]["from"]["name"] == "Storage room"
    assert history[1]["payload"]["to"]["name"] == "Kitchen"


async def test_an_unknown_entity_is_not_found(api: httpx.AsyncClient) -> None:
    response = await api.get("/entities/01a20d66-0000-7000-8000-000000000000")

    assert response.status_code == 404

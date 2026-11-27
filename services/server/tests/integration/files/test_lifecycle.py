"""Attachments, covers, the trash and what the history tells (docs/design/documents.md, 3 and 8)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import delete

from penaria.features.support.documents.infra.orm import AttachmentDB
from penaria.features.support.documents.use_cases import sweep as sweep_module
from penaria.integrations.s3.storage import S3Storage
from tests import images
from tests.integration.apps.api.test_people import make_home, member, ok
from tests.integration.files.conftest import Run
from tests.integration.files.helpers import detail, file_events, listed, row, set_columns, upload
from tests.integration.helpers import NewClient, uow_of
from tests.integration.storage import keys

pytestmark = pytest.mark.integration


async def entries(client: httpx.AsyncClient, entity_id: str) -> list[tuple[str, bool]]:
    """The names of the entity's files, and which is its cover."""
    found = await ok(await client.get(f"/entities/{entity_id}/files"))
    return [(file["name"], file["is_cover"]) for file in found["files"]]


async def trash(client: httpx.AsyncClient, home_id: str) -> list[tuple[str, list[str]]]:
    found = await ok(await client.get(f"/homes/{home_id}/files/trash"))
    return [(file["name"], [place["names"][-1] for place in file["entities"]]) for file in found]


async def test_the_first_photo_is_the_cover_until_one_is_chosen(api: httpx.AsyncClient, worker: Run) -> None:
    ids = await make_home(api)
    towels = ids["towels"]
    manual = await upload(api, towels, "manual.pdf", images.pdf(), kind="manual")
    await upload(api, towels, "one.jpg", images.jpeg())
    two = await upload(api, towels, "two.jpg", images.jpeg())
    processing = await api.put(f"/entities/{towels}/cover", json={"file_id": two["id"]})
    await worker()

    first = await entries(api, towels)
    await ok(await api.put(f"/entities/{towels}/cover", json={"file_id": two["id"]}), 204)
    chosen = await entries(api, towels)
    document = await api.put(f"/entities/{towels}/cover", json={"file_id": manual["id"]})

    assert (processing.status_code, processing.json()["code"]) == (409, "file_processing")
    assert first == [("manual.pdf", False), ("one.jpg", True), ("two.jpg", False)]
    assert chosen == [("manual.pdf", False), ("one.jpg", False), ("two.jpg", True)]
    # A PDF is no image, even one with a preview.
    assert (document.status_code, document.json()["code"]) == (400, "cover_not_an_image")


async def test_one_file_holds_for_several_things_until_the_last_lets_go(
    api: httpx.AsyncClient, worker: Run, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    receipt = (await upload(api, ids["towels"], "bill.pdf", images.pdf(), kind="receipt"))["id"]
    await worker()

    attached = await ok(await api.put(f"/entities/{ids['kitchen']}/files/{receipt}"))
    again = await ok(await api.put(f"/entities/{ids['kitchen']}/files/{receipt}"))
    await ok(await api.delete(f"/entities/{ids['towels']}/files/{receipt}"), 204)
    kept = await detail(api, receipt)
    empty_trash = await trash(api, ids["home"])
    await ok(await api.delete(f"/entities/{ids['kitchen']}/files/{receipt}"), 204)

    # By their paths: the towels are in the guest room, which sorts before the kitchen.
    assert [p["names"][-1] for p in attached["entities"]] == ["Towels", "Kitchen"]
    assert again == attached
    assert [p["names"][-1] for p in kept["entities"]] == ["Kitchen"]
    assert kept["removed_at"] is None
    assert empty_trash == []
    assert await listed(api, ids["kitchen"]) == []
    # Detached from its last place, it is in the trash, which remembers where it was.
    assert await trash(api, ids["home"]) == [("bill.pdf", ["Kitchen"])]
    assert await file_events(container) == [
        ("file.added", ids["towels"]),
        ("file.attached", ids["kitchen"]),
        ("file.detached", ids["towels"]),
        ("file.removed", ids["kitchen"]),
    ]


async def test_a_removed_file_comes_back_where_it_was(
    api: httpx.AsyncClient, new_client: NewClient, worker: Run, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    photo = (await upload(api, ids["towels"], "towels.jpg", images.jpeg()))["id"]
    await ok(await api.put(f"/entities/{ids['kitchen']}/files/{photo}"))
    await worker()
    await ok(await api.put(f"/entities/{ids['towels']}/cover", json={"file_id": photo}), 204)
    maria = await member(api, new_client, ids["home"], "family", "maria")
    contractor = await member(api, new_client, ids["home"], "contractor", "electrician")

    await ok(await api.delete(f"/files/{photo}"), 204)
    removed = await detail(api, photo)
    twice = await api.delete(f"/files/{photo}")
    renamed = await api.patch(f"/files/{photo}", json={"name": "x.jpg"})
    covers = await ok(await api.post("/covers:find", json={"entity_ids": [ids["towels"], ids["kitchen"]]}))

    assert removed["removed_at"] is not None
    purge_at = datetime.fromisoformat(removed["purge_at"])
    assert purge_at - datetime.fromisoformat(removed["removed_at"]) == timedelta(days=30)
    assert [(r.status_code, r.json()["code"]) for r in (twice, renamed)] == [(409, "file_removed")] * 2
    assert covers == []
    assert await listed(api, ids["towels"]) == []
    # Only who could restore it finds it in the trash, and may still look at it there.
    assert await trash(maria, ids["home"]) == [("towels.jpg", ["Towels", "Kitchen"])]
    assert (await maria.get(f"/files/{photo}/preview/320")).status_code == 200
    assert await trash(contractor, ids["home"]) == []
    assert (await contractor.get(f"/files/{photo}/content")).status_code == 404

    restored = await ok(await maria.post(f"/files/{photo}:restore"))
    again = await maria.post(f"/files/{photo}:restore")

    assert restored["removed_at"] is None
    # It was the chosen cover of the towels; being removed, it stopped being one.
    assert [place["is_cover"] for place in restored["entities"]] == [False, False]
    assert (again.status_code, again.json()["code"]) == (409, "file_not_removed")
    assert await listed(api, ids["towels"]) == ["towels.jpg"]
    assert await listed(api, ids["kitchen"]) == ["towels.jpg"]
    assert (await contractor.get(f"/files/{photo}/content")).status_code == 200
    assert [type_ for type_, _ in await file_events(container)] == [
        "file.added",
        "file.attached",
        "file.cover_set",
        "file.removed",
        "file.removed",
        "file.restored",
        "file.restored",
    ]


async def test_thirty_days_in_the_trash_and_the_file_is_gone_for_good(
    api: httpx.AsyncClient, worker: Run, sweep: Run, container: DishkaContainer, storage: S3Storage
) -> None:
    ids = await make_home(api)
    photo = (await upload(api, ids["towels"], "old.jpg", images.jpeg()))["id"]
    fresh = (await upload(api, ids["towels"], "fresh.jpg", images.jpeg()))["id"]
    await worker()
    for file_id in (photo, fresh):
        await ok(await api.delete(f"/files/{file_id}"), 204)
    await set_columns(container, photo, removed_at=datetime.now(UTC) - timedelta(days=30, minutes=1))

    # Past its time it is gone for people at once, whether the worker has come by or not.
    before = await trash(api, ids["home"])
    late = await api.post(f"/files/{photo}:restore")
    await sweep()

    assert before == [("fresh.jpg", ["Towels"])]
    assert (late.status_code, late.json()["code"]) == (404, "file_not_found")
    assert await keys(storage, f"files/{photo}/") == []
    assert len(await keys(storage, f"files/{fresh}/")) == 3
    async with (await uow_of(container)).query() as tx:
        left = await tx.files.get_many([UUID(photo), UUID(fresh)])
    assert list(left) == [UUID(fresh)]


async def test_files_that_no_place_holds_go_to_the_trash(
    api: httpx.AsyncClient, worker: Run, sweep: Run, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    photo = (await upload(api, ids["towels"], "towels.jpg", images.jpeg()))["id"]
    await worker()
    # What deleting an entity does to its attachments (the foreign key cascades).
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(delete(AttachmentDB))

    await sweep()

    assert (await row(container, photo)).removed_at is not None
    assert (await api.get(f"/files/{photo}")).status_code == 404
    assert await trash(api, ids["home"]) == []


async def test_uploads_nothing_waits_for_are_forgotten(
    api: httpx.AsyncClient, sweep: Run, storage: S3Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await make_home(api)
    waiting = (await upload(api, ids["towels"], "waiting.jpg", images.jpeg()))["id"]
    abandoned = "01900000-0000-7000-8000-000000000000"

    async def content() -> Any:
        yield b"left by a request that never finished"

    await storage.put(f"incoming/{abandoned}", content(), content_type="image/jpeg")
    await sweep()
    young = await keys(storage, "incoming/")
    monkeypatch.setattr(sweep_module, "ABANDONED_UPLOAD_AGE", timedelta(minutes=-1))
    await sweep()

    assert f"incoming/{abandoned}" in young
    assert f"incoming/{abandoned}" not in await keys(storage, "incoming/")
    assert f"incoming/{waiting}" in await keys(storage, "incoming/")


async def test_an_archived_thing_keeps_its_files_and_gets_no_new_ones(api: httpx.AsyncClient, worker: Run) -> None:
    ids = await make_home(api)
    towels = ids["towels"]
    receipt = (await upload(api, towels, "bill.pdf", images.pdf(), kind="receipt"))["id"]
    other = (await upload(api, ids["kitchen"], "other.txt", b"text", kind="other"))["id"]
    await worker()
    await ok(await api.post(f"/entities/{towels}:archive", json={"reason": "discarded", "version": 1}))

    found = await ok(await api.get(f"/entities/{towels}/files"))
    added = await upload(api, towels, "new.jpg", images.jpeg(), status=409)
    attached = await api.put(f"/entities/{towels}/files/{other}")

    assert ([f["name"] for f in found["files"]], found["add_kinds"]) == (["bill.pdf"], [])
    assert (added["code"], attached.json()["code"]) == ("entity_archived", "entity_archived")
    assert (await api.get(f"/files/{receipt}/content")).status_code == 200


async def history(client: httpx.AsyncClient, entity_id: str) -> list[tuple[str, Any]]:
    """The file events of an entity's history: the type and the name it tells, if it does."""
    events = await ok(await client.get(f"/entities/{entity_id}/history"))
    return [
        (event["type"], event["payload"]["file"] and event["payload"]["file"]["name"])
        for event in events
        if event["type"].startswith("file.")
    ]


async def test_history_names_a_file_only_to_those_who_may_see_it(
    api: httpx.AsyncClient, new_client: NewClient, sweep: Run, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    towels = ids["towels"]
    manual = (await upload(api, towels, "manual.pdf", images.pdf(), kind="manual"))["id"]
    receipt = (await upload(api, towels, "bill 120.pdf", images.pdf(), kind="receipt"))["id"]
    await ok(await api.patch(f"/files/{receipt}", json={"name": "bill 99.pdf"}))
    contractor = await member(api, new_client, ids["home"], "contractor", "electrician")
    maria = await member(api, new_client, ids["home"], "family", "maria")

    seen = await history(contractor, towels)
    changes = await ok(await contractor.get(f"/entities/{towels}/history"))

    assert await history(api, towels) == [
        ("file.changed", "bill 99.pdf"),
        ("file.added", "bill 120.pdf"),
        ("file.added", "manual.pdf"),
    ]
    assert seen == [("file.changed", None), ("file.added", None), ("file.added", "manual.pdf")]
    assert next(e for e in changes if e["type"] == "file.changed")["payload"] == {"file": None, "changes": None}

    # Deleted for good, a file is named only to those who may see every file there.
    for file_id in (manual, receipt):
        await ok(await api.delete(f"/files/{file_id}"), 204)
        await set_columns(container, file_id, removed_at=datetime.now(UTC) - timedelta(days=31))
    await sweep()

    assert [name for _, name in await history(contractor, towels)] == [None] * 5
    # She sees receipts but nothing private, so not every file there could have been hers to see.
    assert [name for _, name in await history(maria, towels)] == [None] * 5
    assert [name for _, name in await history(api, towels)] == [
        "bill 99.pdf",
        "manual.pdf",
        "bill 99.pdf",
        "bill 120.pdf",
        "manual.pdf",
    ]


async def test_what_a_command_refuses(api: httpx.AsyncClient, worker: Run) -> None:
    ids = await make_home(api)
    towels, kitchen = ids["towels"], ids["kitchen"]
    photo = (await upload(api, towels, "one.jpg", images.jpeg()))["id"]
    manual = (await upload(api, towels, "manual.pdf", images.pdf(), kind="manual"))["id"]
    broken = (await upload(api, towels, "broken.jpg", images.jpeg()[:300]))["id"]
    gone = (await upload(api, towels, "gone.txt", b"text", kind="other"))["id"]
    await worker()
    await ok(await api.delete(f"/files/{gone}"), 204)

    refused = [
        await api.put(f"/entities/{kitchen}/files/{gone}"),
        await api.delete(f"/entities/{kitchen}/files/{photo}"),
        await api.put(f"/entities/{towels}/cover", json={"file_id": broken}),
        await api.put(f"/entities/{kitchen}/cover", json={"file_id": photo}),
        await api.patch(f"/files/{manual}", json={"kind": "photo"}),
    ]
    await ok(await api.post(f"/entities/{towels}:archive", json={"reason": "discarded", "version": 1}))
    on_archived = await api.put(f"/entities/{towels}/cover", json={"file_id": photo})

    assert [(r.status_code, r.json()["code"]) for r in [*refused, on_archived]] == [
        (409, "file_removed"),
        (404, "file_not_found"),
        (409, "file_failed"),
        (404, "file_not_found"),
        (400, "not_a_photo"),
        (409, "entity_archived"),
    ]


async def test_a_change_that_changes_nothing_is_not_journalled(
    api: httpx.AsyncClient, worker: Run, container: DishkaContainer
) -> None:
    ids = await make_home(api)
    photo = (await upload(api, ids["towels"], "one.jpg", images.jpeg()))["id"]
    await worker()

    await ok(await api.patch(f"/files/{photo}", json={"name": "one.jpg", "kind": "photo", "visibility": "guests"}))
    for _ in range(2):
        await ok(await api.put(f"/entities/{ids['towels']}/cover", json={"file_id": photo}), 204)

    assert [type_ for type_, _ in await file_events(container)] == ["file.added", "file.cover_set"]

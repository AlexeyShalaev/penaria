"""What the tests of files share."""

from typing import Any

import httpx
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy import select, update

from penaria.features.support.documents.infra.orm import FileDB
from penaria.features.support.platform.infra.orm import JournalEventDB
from tests.integration.apps.api.test_people import ok
from tests.integration.helpers import uow_of


async def upload(
    client: httpx.AsyncClient, entity_id: str, name: str, data: bytes, kind: str = "photo", status: int = 201
) -> Any:
    response = await client.post(f"/entities/{entity_id}/files", params={"kind": kind}, files={"file": (name, data)})
    return await ok(response, status)


async def listed(client: httpx.AsyncClient, entity_id: str) -> list[str]:
    """The names of the entity's files the client sees."""
    return [file["name"] for file in (await ok(await client.get(f"/entities/{entity_id}/files")))["files"]]


async def detail(client: httpx.AsyncClient, file_id: str) -> Any:
    return await ok(await client.get(f"/files/{file_id}"))


async def row(container: DishkaContainer, file_id: str) -> FileDB:
    async with (await uow_of(container)).query() as tx:
        found = await tx.session.scalar(select(FileDB).where(FileDB.id == file_id))
    assert found is not None
    return found


async def set_columns(container: DishkaContainer, file_id: str, **values: Any) -> None:
    async with (await uow_of(container)).transaction() as tx:
        await tx.session.execute(update(FileDB).where(FileDB.id == file_id).values(**values))


async def file_events(container: DishkaContainer) -> list[tuple[str, str]]:
    """The file events of the journal, the oldest first: the type and the entity it is about."""
    async with (await uow_of(container)).query() as tx:
        rows = await tx.session.execute(
            select(JournalEventDB.type, JournalEventDB.entity_id)
            .where(JournalEventDB.type.startswith("file."))
            .order_by(JournalEventDB.seq)
        )
        return [(type_, str(entity_id)) for type_, entity_id in rows]

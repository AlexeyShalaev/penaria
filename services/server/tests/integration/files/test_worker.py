"""The worker's queue: leases, attempts, crashes, storage failures and several workers at once."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from servicewright.adapters.dishka import DishkaContainer
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from penaria.apps.worker.container import build_container
from penaria.apps.worker.settings import Settings as WorkerSettings
from penaria.features.shared.homes import HomeTimezones
from penaria.features.support.documents.domain.processing import (
    RETRY_DELAY,
    Rendered,
    Renderer,
    RendererCrashedError,
)
from penaria.features.support.documents.domain.storage import ObjectStorage, StorageUnavailableError
from penaria.features.support.documents.infra.sandbox import SandboxRenderer
from penaria.features.support.documents.use_cases import processing
from penaria.features.support.documents.use_cases.processing import ProcessNextFile
from penaria.features.support.identity.use_cases.homes import IdentityHomeTimezones
from penaria.integrations.postgres.transaction import PenariaTransaction
from penaria.integrations.s3.settings import S3Settings
from penaria.integrations.s3.storage import S3Storage, open_s3
from tests import images
from tests.integration.apps.api.test_people import make_home, ok
from tests.integration.files.conftest import Run
from tests.integration.files.helpers import detail, row, set_columns, upload
from tests.integration.helpers import uow_of
from tests.integration.storage import keys

pytestmark = pytest.mark.integration


class Crashing(Renderer):
    def __init__(self) -> None:
        self.calls = 0

    async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
        self.calls += 1
        raise RendererCrashedError("the renderer ended with signal SIGSEGV")


class Stuck(Renderer):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("never reached")


class Counting(Renderer):
    def __init__(self) -> None:
        self.sources: list[bytes] = []

    async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
        self.sources.append(source.read_bytes())
        await asyncio.sleep(0.05)
        return Rendered()


class FailingStorage:
    """A storage that answers nothing, as one that is restarting."""

    def __init__(self, real: ObjectStorage) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    async def download(self, key: str, path: Path) -> None:
        raise StorageUnavailableError("the storage is away")


@pytest.fixture
async def parts(
    migrated_database: None, worker_settings: WorkerSettings, s3_variables: dict[str, Any]
) -> AsyncIterator[tuple[Any, ObjectStorage, HomeTimezones]]:
    """The worker's unit of work, storage and time zones, to use with a renderer of the test's own."""
    container = build_container(worker_settings)
    async with container.app_scope() as scope:
        uow = await scope.get(AsyncSQLAlchemyUnitOfWork[PenariaTransaction])
        timezones = IdentityHomeTimezones(uow)
        async with open_s3(S3Settings.model_validate(s3_variables)) as objects:
            yield uow, objects, timezones


async def one_upload(api: httpx.AsyncClient, kind: str = "photo", data: bytes = images.jpeg()) -> str:
    ids = await make_home(api)
    return str((await upload(api, ids["towels"], "a.jpg", data, kind=kind))["id"])


async def test_a_file_that_crashes_the_renderer_is_given_up_after_three_tries(
    api: httpx.AsyncClient,
    parts: tuple[Any, ObjectStorage, HomeTimezones],
    storage: S3Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(processing, "RETRY_DELAY", timedelta())
    file_id = await one_upload(api)
    uow, objects, zones = parts
    renderer = Crashing()
    processor = ProcessNextFile(uow, objects, renderer, zones)

    taken = 0
    while await processor.execute():
        taken += 1

    failed = await detail(api, file_id)
    assert (renderer.calls, taken) == (3, 3)
    assert (failed["status"], failed["failure"]) == ("failed", "processing_failed")
    assert await keys(storage, f"incoming/{file_id}") == []


async def test_a_crashed_file_waits_before_its_next_try(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones], container: DishkaContainer
) -> None:
    file_id = await one_upload(api)
    uow, objects, zones = parts
    processor = ProcessNextFile(uow, objects, Crashing(), zones)

    assert await processor.execute() is True
    assert await processor.execute() is False

    waiting = await row(container, file_id)
    assert (waiting.status, waiting.attempts) == ("processing", 1)
    assert waiting.leased_until is not None
    assert waiting.leased_until > datetime.now(UTC)


async def test_a_file_that_took_the_worker_down_every_time_is_not_tried_again(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones], container: DishkaContainer
) -> None:
    file_id = await one_upload(api)
    # Three workers took it and never said how it went: their leases have run out.
    await set_columns(container, file_id, attempts=3, leased_until=datetime.now(UTC) - timedelta(seconds=1))
    uow, objects, zones = parts
    renderer = Counting()

    await ProcessNextFile(uow, objects, renderer, zones).execute()

    assert renderer.sources == []
    assert (await detail(api, file_id))["failure"] == "processing_failed"


async def test_a_storage_that_is_away_costs_no_attempt(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones], container: DishkaContainer
) -> None:
    file_id = await one_upload(api)
    uow, objects, zones = parts

    await ProcessNextFile(uow, FailingStorage(objects), Counting(), zones).execute()

    waiting = await row(container, file_id)
    assert (waiting.status, waiting.attempts) == ("processing", 0)
    assert waiting.leased_until is not None


async def test_a_worker_that_is_stopped_gives_its_file_back_at_once(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones], container: DishkaContainer
) -> None:
    file_id = await one_upload(api)
    uow, objects, zones = parts
    renderer = Stuck()
    running = asyncio.create_task(ProcessNextFile(uow, objects, renderer, zones).execute())
    await renderer.started.wait()

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    waiting = await row(container, file_id)
    assert (waiting.status, waiting.attempts, waiting.leased_until) == ("processing", 0, None)


async def test_several_workers_never_take_the_same_file(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones]
) -> None:
    ids = await make_home(api)
    contents = [f"note {number}".encode() * 20 for number in range(6)]
    for number, content in enumerate(contents):
        await upload(api, ids["towels"], f"{number}.pdf", b"%PDF-" + content, kind="manual")
    uow, objects, zones = parts
    renderer = Counting()

    async def drain() -> None:
        processor = ProcessNextFile(uow, objects, renderer, zones)
        while await processor.execute():
            pass

    await asyncio.gather(drain(), drain(), drain())

    assert sorted(renderer.sources) == sorted(b"%PDF-" + content for content in contents)


async def test_a_worker_whose_lease_ran_out_writes_nothing(
    api: httpx.AsyncClient,
    parts: tuple[Any, ObjectStorage, HomeTimezones],
    container: DishkaContainer,
    storage: S3Storage,
) -> None:
    file_id = await one_upload(api)
    uow, objects, zones = parts

    class Overtaken(Renderer):
        async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
            # Meanwhile the lease ran out and another worker took the file.
            await set_columns(container, file_id, attempts=2)
            return Rendered()

    await ProcessNextFile(uow, objects, Overtaken(), zones).execute()

    assert (await row(container, file_id)).status == "processing"
    # The other worker still needs the upload.
    assert await keys(storage, f"incoming/{file_id}") == [f"incoming/{file_id}"]


async def test_a_file_deleted_while_it_was_processed_leaves_nothing_in_storage(
    api: httpx.AsyncClient,
    parts: tuple[Any, ObjectStorage, HomeTimezones],
    container: DishkaContainer,
    storage: S3Storage,
) -> None:
    # A PDF, which the worker renders but does not require a clean copy of.
    file_id = await one_upload(api, kind="manual", data=b"%PDF-1.7 soon gone")
    uow, objects, zones = parts

    class Deleting(Renderer):
        async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
            async with (await uow_of(container)).transaction() as tx:
                await tx.files.delete(UUID(file_id))
            return Rendered()

    await ProcessNextFile(uow, objects, Deleting(), zones).execute()

    assert await keys(storage, f"files/{file_id}/") == []
    assert await keys(storage, f"incoming/{file_id}") == []


async def test_a_rename_made_while_the_file_is_processed_is_kept(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones]
) -> None:
    ids = await make_home(api)
    added = await upload(api, ids["towels"], "IMG_0001.HEIC", images.heic())
    uow, objects, zones = parts

    class Renaming(Renderer):
        async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
            await ok(await api.patch(f"/files/{added['id']}", json={"name": "Kettle.heic"}))
            return await SandboxRenderer().render(source, media_type, into)

    await ProcessNextFile(uow, objects, Renaming(), zones).execute()

    ready = await detail(api, added["id"])
    # The new name, with the extension of what the file became.
    assert (ready["status"], ready["name"]) == ("ready", "Kettle.jpg")


async def test_a_retry_waits_from_the_crash_not_from_the_start(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones], container: DishkaContainer
) -> None:
    file_id = await one_upload(api)
    uow, objects, zones = parts
    crashed_at: list[datetime] = []

    class Slow(Renderer):
        async def render(self, source: Path, media_type: str, into: Path) -> Rendered:
            await asyncio.sleep(0.2)
            crashed_at.append(datetime.now(UTC))
            raise RendererCrashedError("rendering took longer than 120 s")

    await ProcessNextFile(uow, objects, Slow(), zones).execute()

    leased_until = (await row(container, file_id)).leased_until
    assert leased_until is not None
    assert leased_until >= crashed_at[0] + RETRY_DELAY


async def test_an_image_without_a_clean_copy_is_never_stored_as_it_came(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones], storage: S3Storage
) -> None:
    file_id = await one_upload(api)
    uow, objects, zones = parts

    # Counting answers as if there were nothing to clean.
    await ProcessNextFile(uow, objects, Counting(), zones).execute()

    assert (await detail(api, file_id))["status"] == "processing"
    assert await keys(storage, f"files/{file_id}/") == []


async def test_a_damaged_pdf_is_kept_without_a_preview(api: httpx.AsyncClient, worker: Run) -> None:
    file_id = await one_upload(api, kind="manual", data=b"%PDF-1.7 nothing a viewer could draw")

    await worker()

    ready = await detail(api, file_id)
    assert (ready["status"], ready["has_preview"]) == ("ready", False)


async def test_an_upload_missing_from_storage_fails_its_file(
    api: httpx.AsyncClient, worker: Run, storage: S3Storage
) -> None:
    file_id = await one_upload(api)
    await storage.delete([f"incoming/{file_id}"])

    await worker()

    assert (await detail(api, file_id))["failure"] == "content_missing"


async def test_a_pdf_that_cannot_be_drawn_is_kept_without_a_preview(
    api: httpx.AsyncClient, parts: tuple[Any, ObjectStorage, HomeTimezones]
) -> None:
    file_id = await one_upload(api, kind="manual", data=b"%PDF-1.7 locked with a password")
    uow, objects, zones = parts

    await ProcessNextFile(uow, objects, Crashing(), zones).execute()

    ready = await detail(api, file_id)
    assert (ready["status"], ready["has_preview"]) == ("ready", False)
    assert (await api.get(f"/files/{file_id}/content")).content == b"%PDF-1.7 locked with a password"

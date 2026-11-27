"""The worker's side of an upload: take a file from the queue, clean it, preview it, and say how it went
(docs/design/documents.md, 5)."""

import asyncio
import hashlib
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.homes import HomeTimezones
from penaria.features.support.documents.domain.files import (
    HEIC,
    PDF,
    UPLOADED_IMAGES,
    File,
    FileFailure,
    FileStatus,
    name_as_jpeg,
)
from penaria.features.support.documents.domain.processing import (
    LEASE,
    MAX_ATTEMPTS,
    RETRY_DELAY,
    Rendered,
    Renderer,
    RendererCrashedError,
    UnrenderableError,
)
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.domain.storage import (
    PREVIEW_TYPE,
    ObjectMissingError,
    ObjectStorage,
    StorageUnavailableError,
    incoming_key,
    keys_of,
    original_key,
    preview_key,
)

logger = logging.getLogger(__name__)


class ProcessNextFile:
    """Safe in several workers at once: each file is taken under a lease, and its outcome is written only
    by the worker that still holds it. Running it again for the same file writes the same objects."""

    def __init__(
        self,
        uow: AsyncUnitOfWork[DocumentsTransaction],
        storage: ObjectStorage,
        renderer: Renderer,
        timezones: HomeTimezones,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._renderer = renderer
        self._timezones = timezones

    async def execute(self) -> bool:
        """Process the oldest waiting file; False if none waits."""
        now = datetime.now(UTC)
        async with self._uow.transaction() as tx:
            file = await tx.files.claim(now, now + LEASE)
        if file is None:
            return False
        try:
            if file.attempts > MAX_ATTEMPTS:
                await self._fail(file, FileFailure.PROCESSING_FAILED)
            else:
                await self._process(file)
        except StorageUnavailableError:
            logger.warning("The storage failed while processing file %s; it is tried again", file.id)
            await self._give_back(file, datetime.now(UTC) + RETRY_DELAY)
        except RendererCrashedError as exc:
            logger.warning("Processing file %s crashed (attempt %d): %s", file.id, file.attempts, exc)
            if file.attempts >= MAX_ATTEMPTS:
                await self._fail(file, FileFailure.PROCESSING_FAILED)
            else:
                async with self._uow.transaction() as tx:
                    # From now, not from when it was taken: a render may have used up its deadline.
                    await tx.files.postpone(file, datetime.now(UTC) + RETRY_DELAY)
        except asyncio.CancelledError:
            # The worker is stopping: another one, or this one after its restart, takes the file at once.
            await asyncio.shield(self._give_back(file, None))
            raise
        return True

    async def _process(self, file: File) -> None:
        with tempfile.TemporaryDirectory(prefix="penaria-") as directory:
            work = Path(directory)
            source = work / "upload"
            try:
                await self._storage.download(incoming_key(file.id), source)
            except ObjectMissingError:
                await self._fail(file, FileFailure.CONTENT_MISSING)
                return
            try:
                rendered = await self._render(file, source, work)
            except UnrenderableError as exc:
                logger.info("File %s cannot be processed (%s): %s", file.id, exc.reason, exc)
                await self._fail(file, exc.reason)
                return
            await self._store(file, source, rendered)

    async def _render(self, file: File, source: Path, work: Path) -> Rendered:
        if file.media_type in UPLOADED_IMAGES:
            rendered = await self._renderer.render(source, file.media_type, work)
            # Never the upload in place of the clean copy: it still says where the photo was taken.
            if rendered.original is None:
                raise RendererCrashedError("the renderer produced no cleaned original of an image")
            return rendered
        if file.media_type == PDF:
            # A PDF is kept byte for byte whether or not its first page can be drawn.
            try:
                return await self._renderer.render(source, file.media_type, work)
            except (UnrenderableError, RendererCrashedError) as exc:
                logger.info("File %s gets no preview: %s", file.id, exc)
        return Rendered()

    async def _store(self, file: File, source: Path, rendered: Rendered) -> None:
        original = source if rendered.original is None else rendered.original
        converted = file.media_type == HEIC
        file.media_type = rendered.media_type or file.media_type
        file.size = original.stat().st_size
        file.sha256 = await asyncio.to_thread(_sha256, original)
        file.width, file.height = rendered.width, rendered.height
        file.taken_at = await self._when_taken(file, rendered.taken_at)
        file.previews = bool(rendered.previews)
        file.status = FileStatus.READY
        await self._storage.put_file(original_key(file.id), original, content_type=file.media_type)
        for size, preview in rendered.previews.items():
            await self._storage.put_file(preview_key(file.id, size), preview, content_type=PREVIEW_TYPE)
        await self._finish(file, converted=converted)

    async def _when_taken(self, file: File, taken_at: datetime | None) -> datetime | None:
        """A camera that notes no offset writes the time of where it is: the home's, for a home's photos."""
        if taken_at is None or taken_at.tzinfo is not None:
            return taken_at
        zone = await self._timezones.timezone(file.home_id)
        return None if zone is None else taken_at.replace(tzinfo=zone)

    async def _fail(self, file: File, reason: FileFailure) -> None:
        file.status = FileStatus.FAILED
        file.failure = reason
        await self._finish(file)

    async def _finish(self, file: File, *, converted: bool = False) -> None:
        async with self._uow.transaction() as tx:
            # The name as it is now: someone may have renamed the file while it was processed.
            current = await tx.files.get(file.id, for_update=True)
            if current is not None:
                file.name = name_as_jpeg(current.name) if converted else current.name
            written = current is not None and await tx.files.finish(file)
            gone = current is None
        if written:
            # Nothing may read the upload again: the clean original stands for it, or nothing does.
            await self._storage.delete([incoming_key(file.id)])
        elif gone:
            # Deleted while it was processed.
            await self._storage.delete(keys_of(file.id))

    async def _give_back(self, file: File, until: datetime | None) -> None:
        async with self._uow.transaction() as tx:
            await tx.files.give_back(file, until)


def _sha256(path: Path) -> str:
    with path.open("rb") as content:
        return hashlib.file_digest(content, "sha256").hexdigest()

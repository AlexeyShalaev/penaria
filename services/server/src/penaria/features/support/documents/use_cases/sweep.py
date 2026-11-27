"""The worker's housekeeping: empties the trash of what is past its 30 days, and forgets uploads that
never became files (docs/design/documents.md, 8)."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.support.documents.domain.files import TRASH_RETENTION
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.domain.storage import INCOMING_PREFIX, ObjectStorage, keys_of

PURGE_BATCH = 100
# An upload older than this that no file waits for was left by an interrupted request.
ABANDONED_UPLOAD_AGE = timedelta(days=1)

logger = logging.getLogger(__name__)


class SweepFiles:
    """Safe in several workers at once: whatever two of them delete is deleted once."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], storage: ObjectStorage) -> None:
        self._uow = uow
        self._storage = storage

    async def execute(self) -> None:
        now = datetime.now(UTC)
        # A deleted entity takes its attachments with it; what nothing holds any more goes to the trash.
        async with self._uow.transaction() as tx:
            unattached = await tx.files.remove_unattached(now)
        if unattached:
            logger.info("%d files held by nothing went to the trash", unattached)
        await self._purge(now - TRASH_RETENTION)
        await self._forget_abandoned_uploads(now - ABANDONED_UPLOAD_AGE)

    async def _purge(self, removed_before: datetime) -> None:
        while True:
            async with self._uow.query() as tx:
                expired = await tx.files.removed_before(removed_before, PURGE_BATCH)
            if not expired:
                return
            # The objects first: a file whose deletion stops half way is deleted again, not forgotten.
            await self._storage.delete([key for file_id in expired for key in keys_of(file_id)])
            async with self._uow.transaction() as tx:
                for file_id in expired:
                    await tx.files.delete(file_id)
            logger.info("Deleted %d files that were in the trash for 30 days", len(expired))

    async def _forget_abandoned_uploads(self, before: datetime) -> None:
        keys = {}
        for key in await self._storage.older_than(INCOMING_PREFIX, before):
            try:
                keys[UUID(key.removeprefix(INCOMING_PREFIX))] = key
            except ValueError:
                logger.warning("The storage holds an object Penaria did not make: %s", key)
        if not keys:
            return
        async with self._uow.query() as tx:
            waiting = await tx.files.still_processing(keys.keys())
        await self._storage.delete([key for file_id, key in keys.items() if file_id not in waiting])

"""What the documents use cases need from storage."""

from collections.abc import Collection
from datetime import datetime
from typing import Protocol
from uuid import UUID

from penaria.features.shared.journal import Journal
from penaria.features.support.documents.domain.files import Attachment, File


class FileRepository(Protocol):
    async def get(self, file_id: UUID, *, for_update: bool = False) -> File | None: ...

    async def get_many(self, file_ids: Collection[UUID]) -> dict[UUID, File]: ...

    async def add(self, file: File) -> None: ...

    async def save(self, file: File) -> None:
        """Write a file's kind, name, visibility and whether it is removed."""
        ...

    async def delete(self, file_id: UUID) -> None:
        """Forget the file and its attachments."""
        ...

    async def attachments_of(self, file_ids: Collection[UUID]) -> dict[UUID, list[Attachment]]:
        """The attachments of each of the files; a file without any is left out."""
        ...

    async def attached_to(self, entity_ids: Collection[UUID]) -> list[tuple[Attachment, File]]:
        """The files attached to the entities that are not in the trash, in each entity's order."""
        ...

    async def attach(self, file_id: UUID, entity_id: UUID) -> None:
        """Attach the file at the end of the entity's list."""
        ...

    async def detach(self, file_id: UUID, entity_id: UUID) -> None: ...

    async def clear_covers_of(self, file_id: UUID) -> None:
        """Stop the file being a cover anywhere."""
        ...

    async def set_cover(self, file_id: UUID, entity_id: UUID) -> None:
        """Make the attached file the entity's one cover."""
        ...

    async def trash_of(self, home_id: UUID, removed_after: datetime) -> list[File]:
        """The home's files removed after ``removed_after``, the latest first."""
        ...

    # The worker's queue.

    async def claim(self, now: datetime, lease_until: datetime) -> File | None:
        """Take the oldest file waiting for processing that no one holds, counting the attempt."""
        ...

    async def give_back(self, file: File, leased_until: datetime | None) -> None:
        """Give a claimed file back without counting the attempt; it waits until ``leased_until``."""
        ...

    async def postpone(self, file: File, until: datetime) -> None:
        """Keep the counted attempt and let the file wait until ``until``."""
        ...

    async def finish(self, file: File) -> bool:
        """Write the outcome of processing; False if the file is gone or another worker has taken it since."""
        ...

    # The sweeps.

    async def remove_unattached(self, now: datetime) -> int:
        """Move the files no entity holds any more (their entities were deleted) to the trash."""
        ...

    async def removed_before(self, before: datetime, limit: int) -> list[UUID]: ...

    async def still_processing(self, file_ids: Collection[UUID]) -> set[UUID]: ...


class DocumentsTransaction(Protocol):
    @property
    def files(self) -> FileRepository: ...

    @property
    def journal(self) -> Journal: ...

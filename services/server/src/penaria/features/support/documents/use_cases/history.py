"""How much of a file's journal events a reader of an entity's history sees (the ``HistoryRedaction`` port)."""

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from sqlalchemy_foundation_kit import AsyncUnitOfWork

from penaria.features.shared.access import Access
from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import RecordedEvent
from penaria.features.support.documents.domain.files import sees_every_file
from penaria.features.support.documents.domain.repositories import DocumentsTransaction
from penaria.features.support.documents.use_cases.access import FileAccess
from penaria.features.support.documents.use_cases.events import FILE_EVENTS


class FileHistoryRedaction:
    """The same rule as for places: an event names a file only to those who may see it as it is now."""

    def __init__(self, uow: AsyncUnitOfWork[DocumentsTransaction], access: FileAccess) -> None:
        self._uow = uow
        self._access = access

    async def redact(self, actor: Actor, access: Access, events: Sequence[RecordedEvent]) -> list[RecordedEvent]:
        named = {_file_id(event) for event in events if event.type.startswith(FILE_EVENTS)}
        if not named:
            return list(events)
        async with self._uow.query() as tx:
            files = await tx.files.get_many(named)
            attachments = await tx.files.attachments_of(files.keys())
        seen = await self._access.see(actor, list(files.values()), attachments)
        shown = {one.file.id for one in seen if one.visible}
        # A file deleted for good has no rules left: it is named only to those who see every file here.
        if sees_every_file(access):
            shown |= named - files.keys()
        return [
            replace(event, payload=_unnamed(event))
            if event.type.startswith(FILE_EVENTS) and _file_id(event) not in shown
            else event
            for event in events
        ]


def _file_id(event: RecordedEvent) -> UUID:
    return UUID(event.payload["file"]["id"])


def _unnamed(event: RecordedEvent) -> dict[str, None]:
    return dict.fromkeys(event.payload)

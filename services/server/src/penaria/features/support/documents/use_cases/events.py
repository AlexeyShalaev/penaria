"""The journal events of files: each names the file as it was called then, and lands in the history of
the entity it is about."""

from typing import Any
from uuid import UUID

from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import Event
from penaria.features.support.documents.domain.files import File

# Every event type of a file starts with this; history.py hides what its reader may not see.
FILE_EVENTS = "file."


def file_event(type_: str, actor: Actor, file: File, entity_id: UUID, changes: dict[str, Any] | None = None) -> Event:
    payload: dict[str, Any] = {
        "file": {"id": str(file.id), "name": file.name, "kind": file.kind.value, "visibility": file.visibility.value}
    }
    if changes is not None:
        payload["changes"] = changes
    return Event(type_, file.home_id, actor, payload, entity_id=entity_id)

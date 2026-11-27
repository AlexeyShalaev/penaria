"""The port through which the feature that writes an event decides how much of it a reader of the journal sees."""

from collections.abc import Sequence
from typing import Protocol

from penaria.features.shared.access import Access
from penaria.features.shared.actor import Actor
from penaria.features.shared.journal import RecordedEvent


class HistoryRedaction(Protocol):
    async def redact(self, actor: Actor, access: Access, events: Sequence[RecordedEvent]) -> list[RecordedEvent]:
        """The events as the actor may read them in the history of an entity where it has ``access``.

        Events of other features pass unchanged.
        """
        ...

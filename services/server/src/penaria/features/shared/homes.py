"""The port through which a feature learns a fact of a home it does not own."""

from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo


class HomeTimezones(Protocol):
    async def timezone(self, home_id: UUID) -> ZoneInfo | None:
        """The home's time zone; None for a home that is gone."""
        ...

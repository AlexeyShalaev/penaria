"""The PostgreSQL journal."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from penaria.features.shared.journal import Event, RecordedEvent
from penaria.features.support.platform.infra.orm import JournalEventDB


class PostgresJournal:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, events: Sequence[Event]) -> None:
        if not events:
            return
        await self._session.execute(
            insert(JournalEventDB),
            [
                {
                    "id": event.id,
                    "home_id": event.home_id,
                    "type": event.type,
                    "version": event.version,
                    "entity_id": event.entity_id,
                    "actor": event.actor.to_json(),
                    "payload": event.payload,
                    "at": event.at,
                }
                for event in events
            ],
        )

    async def for_entity(self, entity_id: UUID, *, limit: int) -> list[RecordedEvent]:
        rows = await self._session.scalars(
            select(JournalEventDB)
            .where(JournalEventDB.entity_id == entity_id)
            .order_by(JournalEventDB.at.desc(), JournalEventDB.seq.desc())
            .limit(limit)
        )
        return [
            RecordedEvent(
                id=row.id,
                type=row.type,
                version=row.version,
                home_id=row.home_id,
                entity_id=row.entity_id,
                actor=row.actor,
                payload=row.payload,
                at=row.at,
            )
            for row in rows
        ]

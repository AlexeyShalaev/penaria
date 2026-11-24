"""The PostgreSQL repository of entities."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from penaria.features.core.registry.domain.entity import Entity
from penaria.features.core.registry.domain.kinds import ArchiveReason, Kind, Privacy, Status
from penaria.features.core.registry.domain.repositories import ChildrenFilter
from penaria.features.core.registry.infra.orm import EntityDB


def to_ltree(path: Sequence[UUID]) -> str:
    """Labels are ids as 32 hex digits: PostgreSQL 15 labels allow no hyphens."""
    return ".".join(entity_id.hex for entity_id in path)


def from_ltree(path: str) -> tuple[UUID, ...]:
    return tuple(UUID(label) for label in path.split("."))


class PostgresEntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: UUID, *, for_update: bool = False) -> Entity | None:
        query = select(EntityDB).where(EntityDB.id == entity_id)
        if for_update:
            query = query.with_for_update()
        row = await self._session.scalar(query)
        return None if row is None else _entity(row)

    async def ancestors(self, entity: Entity) -> list[Entity]:
        above = entity.path[:-1]
        if not above:
            return []
        rows = await self._session.scalars(select(EntityDB).where(EntityDB.id.in_(above)))
        by_id = {row.id: _entity(row) for row in rows}
        return [by_id[entity_id] for entity_id in above]

    async def add(self, entity: Entity) -> None:
        row = EntityDB(id=entity.id)
        _copy(entity, row)
        self._session.add(row)

    async def save(self, entity: Entity) -> None:
        row = await self._session.get(EntityDB, entity.id)
        if row is None:
            raise LookupError(f"entity {entity.id} was never loaded in this transaction")
        _copy(entity, row)

    async def children(self, home_id: UUID, parent_id: UUID | None, filter: ChildrenFilter) -> list[tuple[Entity, int]]:
        child = aliased(EntityDB)
        count_conditions = [child.parent_id == EntityDB.id, child.archived_at.is_(None)]
        conditions = [
            EntityDB.home_id == home_id,
            EntityDB.parent_id == parent_id if parent_id else EntityDB.parent_id.is_(None),
        ]
        if not filter.include_archived:
            conditions.append(EntityDB.archived_at.is_(None))
        if filter.hide_private:
            conditions.append(EntityDB.privacy != Privacy.PRIVATE.value)
            count_conditions.append(child.privacy != Privacy.PRIVATE.value)
        if filter.guest_view:
            # A place shows when it, or something below it, is guest-visible.
            visible = aliased(EntityDB)
            conditions.append(
                exists().where(
                    visible.home_id == home_id,
                    visible.path.op("<@")(EntityDB.path),
                    visible.privacy == Privacy.GUEST_VISIBLE.value,
                    visible.archived_at.is_(None),
                )
            )
        count = select(func.count()).where(*count_conditions).correlate(EntityDB).scalar_subquery()
        rows = await self._session.execute(
            select(EntityDB, count).where(*conditions).order_by(func.lower(EntityDB.name), EntityDB.id)
        )
        return [(_entity(row), children) for row, children in rows]

    async def has_guest_visible_below(self, entity: Entity) -> bool:
        found = await self._session.scalar(
            select(
                exists().where(
                    EntityDB.path.op("<@")(to_ltree(entity.path)),
                    EntityDB.id != entity.id,
                    EntityDB.privacy == Privacy.GUEST_VISIBLE.value,
                    EntityDB.archived_at.is_(None),
                )
            )
        )
        return bool(found)

    async def subtree_height(self, entity: Entity) -> int:
        deepest = await self._session.scalar(
            select(func.max(func.nlevel(EntityDB.path))).where(EntityDB.path.op("<@")(to_ltree(entity.path)))
        )
        return int(deepest or len(entity.path)) - len(entity.path)

    async def move_descendants(self, old_path: Sequence[UUID], new_path: Sequence[UUID]) -> None:
        await self._session.execute(
            text(
                "UPDATE registry_entities"
                " SET path = CAST(:new AS ltree) || subpath(path, :depth)"
                " WHERE path <@ CAST(:old AS ltree) AND nlevel(path) > :depth"
            ),
            {"new": to_ltree(new_path), "old": to_ltree(old_path), "depth": len(old_path)},
        )


def _copy(entity: Entity, row: EntityDB) -> None:
    row.home_id = entity.home_id
    row.kind = entity.kind.value
    row.parent_id = entity.parent_id
    row.path = to_ltree(entity.path)
    row.name = entity.name
    row.aliases = list(entity.aliases)
    row.quantity = entity.quantity
    row.unit = entity.unit
    row.status = entity.status.value
    row.privacy = entity.privacy.value
    row.verified_at = entity.verified_at
    row.verified_by = entity.verified_by
    row.archived_at = entity.archived_at
    row.archive_reason = entity.archive_reason.value if entity.archive_reason else None
    row.version = entity.version


def _entity(row: EntityDB) -> Entity:
    return Entity(
        id=row.id,
        home_id=row.home_id,
        kind=Kind(row.kind),
        parent_id=row.parent_id,
        path=from_ltree(row.path),
        name=row.name,
        aliases=tuple(row.aliases),
        quantity=row.quantity,
        unit=row.unit,
        status=Status(row.status),
        privacy=Privacy(row.privacy),
        verified_at=row.verified_at,
        verified_by=row.verified_by,
        archived_at=row.archived_at,
        archive_reason=ArchiveReason(row.archive_reason) if row.archive_reason else None,
        version=row.version,
    )

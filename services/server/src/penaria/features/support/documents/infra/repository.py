"""The PostgreSQL repository of files and their attachments."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from penaria.features.support.documents.domain.files import (
    Attachment,
    File,
    FileFailure,
    FileKind,
    FileStatus,
    Visibility,
)
from penaria.features.support.documents.infra.orm import AttachmentDB, FileDB


class PostgresFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, file_id: UUID, *, for_update: bool = False) -> File | None:
        query = select(FileDB).where(FileDB.id == file_id).execution_options(populate_existing=True)
        if for_update:
            query = query.with_for_update()
        row = await self._session.scalar(query)
        return None if row is None else _file(row)

    async def get_many(self, file_ids: Collection[UUID]) -> dict[UUID, File]:
        if not file_ids:
            return {}
        rows = await self._session.scalars(select(FileDB).where(FileDB.id.in_(list(file_ids))))
        return {row.id: _file(row) for row in rows}

    async def add(self, file: File) -> None:
        self._session.add(
            FileDB(
                id=file.id,
                home_id=file.home_id,
                kind=file.kind.value,
                visibility=file.visibility.value,
                status=file.status.value,
                name=file.name,
                media_type=file.media_type,
                size=file.size,
                added_by=file.added_by,
                created_at=file.created_at,
            )
        )
        # The attachments reference the row.
        await self._session.flush()

    async def save(self, file: File) -> None:
        await self._session.execute(
            update(FileDB)
            .where(FileDB.id == file.id)
            .values(kind=file.kind.value, name=file.name, visibility=file.visibility.value, removed_at=file.removed_at)
        )

    async def delete(self, file_id: UUID) -> None:
        await self._session.execute(delete(FileDB).where(FileDB.id == file_id))

    async def attachments_of(self, file_ids: Collection[UUID]) -> dict[UUID, list[Attachment]]:
        if not file_ids:
            return {}
        rows = await self._session.scalars(
            select(AttachmentDB)
            .where(AttachmentDB.file_id.in_(list(file_ids)))
            .order_by(AttachmentDB.file_id, AttachmentDB.entity_id)
            .execution_options(populate_existing=True)
        )
        found: dict[UUID, list[Attachment]] = {}
        for row in rows:
            found.setdefault(row.file_id, []).append(_attachment(row))
        return found

    async def attached_to(self, entity_ids: Collection[UUID]) -> list[tuple[Attachment, File]]:
        if not entity_ids:
            return []
        rows = await self._session.execute(
            select(AttachmentDB, FileDB)
            .join(FileDB, FileDB.id == AttachmentDB.file_id)
            .where(AttachmentDB.entity_id.in_(list(entity_ids)), FileDB.removed_at.is_(None))
            .order_by(AttachmentDB.entity_id, AttachmentDB.position, FileDB.id)
        )
        return [(_attachment(attachment), _file(file)) for attachment, file in rows]

    async def attach(self, file_id: UUID, entity_id: UUID) -> None:
        last = await self._session.scalar(
            select(func.max(AttachmentDB.position)).where(AttachmentDB.entity_id == entity_id)
        )
        self._session.add(AttachmentDB(file_id=file_id, entity_id=entity_id, position=0 if last is None else last + 1))
        await self._session.flush()

    async def detach(self, file_id: UUID, entity_id: UUID) -> None:
        await self._session.execute(
            delete(AttachmentDB).where(AttachmentDB.file_id == file_id, AttachmentDB.entity_id == entity_id)
        )

    async def clear_covers_of(self, file_id: UUID) -> None:
        await self._session.execute(update(AttachmentDB).where(AttachmentDB.file_id == file_id).values(is_cover=False))

    async def set_cover(self, file_id: UUID, entity_id: UUID) -> None:
        # Two covers chosen at once wait for each other here, so the unique index never refuses one.
        await self._session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(entity_id), 0))))
        await self._session.execute(
            update(AttachmentDB)
            .where(AttachmentDB.entity_id == entity_id, AttachmentDB.is_cover)
            .values(is_cover=False)
        )
        await self._session.execute(
            update(AttachmentDB)
            .where(AttachmentDB.entity_id == entity_id, AttachmentDB.file_id == file_id)
            .values(is_cover=True)
        )

    async def trash_of(self, home_id: UUID, removed_after: datetime) -> list[File]:
        rows = await self._session.scalars(
            select(FileDB)
            .where(FileDB.home_id == home_id, FileDB.removed_at > removed_after)
            .order_by(FileDB.removed_at.desc(), FileDB.id.desc())
        )
        return [_file(row) for row in rows]

    async def claim(self, now: datetime, lease_until: datetime) -> File | None:
        waiting = (
            select(FileDB.id)
            .where(
                FileDB.status == FileStatus.PROCESSING.value,
                or_(FileDB.leased_until.is_(None), FileDB.leased_until <= now),
            )
            .order_by(FileDB.created_at, FileDB.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = await self._session.scalar(
            update(FileDB)
            .where(FileDB.id.in_(waiting.scalar_subquery()))
            .values(leased_until=lease_until, attempts=FileDB.attempts + 1)
            .returning(FileDB)
            .execution_options(synchronize_session=False)
        )
        return None if row is None else _file(row)

    async def give_back(self, file: File, leased_until: datetime | None) -> None:
        await self._session.execute(
            update(FileDB).where(*_held(file)).values(leased_until=leased_until, attempts=file.attempts - 1)
        )

    async def postpone(self, file: File, until: datetime) -> None:
        await self._session.execute(update(FileDB).where(*_held(file)).values(leased_until=until))

    async def finish(self, file: File) -> bool:
        written = await self._session.execute(
            update(FileDB)
            .where(*_held(file))
            .values(
                status=file.status.value,
                failure=None if file.failure is None else file.failure.value,
                name=file.name,
                media_type=file.media_type,
                size=file.size,
                sha256=file.sha256,
                width=file.width,
                height=file.height,
                taken_at=file.taken_at,
                previews=file.previews,
                leased_until=None,
            )
            .returning(FileDB.id)
        )
        return written.first() is not None

    async def remove_unattached(self, now: datetime) -> int:
        removed = await self._session.execute(
            update(FileDB)
            .where(FileDB.removed_at.is_(None), ~exists().where(AttachmentDB.file_id == FileDB.id).correlate(FileDB))
            .values(removed_at=now)
            .returning(FileDB.id)
        )
        return len(removed.all())

    async def removed_before(self, before: datetime, limit: int) -> list[UUID]:
        rows = await self._session.scalars(
            select(FileDB.id).where(FileDB.removed_at <= before).order_by(FileDB.removed_at, FileDB.id).limit(limit)
        )
        return list(rows)

    async def still_processing(self, file_ids: Collection[UUID]) -> set[UUID]:
        if not file_ids:
            return set()
        rows = await self._session.scalars(
            select(FileDB.id).where(FileDB.id.in_(list(file_ids)), FileDB.status == FileStatus.PROCESSING.value)
        )
        return set(rows)


def _held(file: File) -> tuple[ColumnElement[bool], ...]:
    """The claimed file, unless it was taken again since: each claim counts one attempt more."""
    return (
        FileDB.id == file.id,
        FileDB.status == FileStatus.PROCESSING.value,
        FileDB.attempts == file.attempts,
    )


def _attachment(row: AttachmentDB) -> Attachment:
    return Attachment(file_id=row.file_id, entity_id=row.entity_id, position=row.position, is_cover=row.is_cover)


def _file(row: FileDB) -> File:
    return File(
        id=row.id,
        home_id=row.home_id,
        kind=FileKind(row.kind),
        visibility=Visibility(row.visibility),
        status=FileStatus(row.status),
        failure=None if row.failure is None else FileFailure(row.failure),
        name=row.name,
        media_type=row.media_type,
        size=row.size,
        sha256=row.sha256,
        width=row.width,
        height=row.height,
        taken_at=row.taken_at,
        previews=row.previews,
        added_by=row.added_by,
        created_at=row.created_at,
        removed_at=row.removed_at,
        attempts=row.attempts,
    )

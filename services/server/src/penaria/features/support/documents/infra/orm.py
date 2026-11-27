"""The documents' tables; every one is named documents_*."""

import datetime
import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from penaria.common.database import Base


class FileDB(Base):
    __tablename__ = "documents_files"
    __table_args__ = (
        CheckConstraint("kind IN ('photo', 'receipt', 'warranty', 'manual', 'other')", name="kind"),
        CheckConstraint("visibility IN ('normal', 'private', 'guests')", name="visibility"),
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="status"),
        CheckConstraint("(status = 'failed') = (failure IS NOT NULL)", name="failed_with_reason"),
        CheckConstraint("size >= 0", name="size_not_negative"),
        # The worker's queue, the oldest first.
        Index("documents_files_queue_idx", "created_at", postgresql_where=text("status = 'processing'")),
        # The trash of a home, and what is past its time there.
        Index(
            "documents_files_home_id_removed_at_idx",
            "home_id",
            "removed_at",
            postgresql_where=text("removed_at IS NOT NULL"),
        ),
        Index("documents_files_removed_at_idx", "removed_at", postgresql_where=text("removed_at IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_homes.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    failure: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None]
    height: Mapped[int | None]
    taken_at: Mapped[datetime.datetime | None]
    previews: Mapped[bool] = mapped_column(server_default=text("false"))
    added_by: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime]
    removed_at: Mapped[datetime.datetime | None]
    leased_until: Mapped[datetime.datetime | None]
    attempts: Mapped[int] = mapped_column(server_default=text("0"))


class AttachmentDB(Base):
    __tablename__ = "documents_attachments"
    __table_args__ = (
        Index("documents_attachments_cover_key", "entity_id", unique=True, postgresql_where=text("is_cover")),
        Index("documents_attachments_entity_id_position_idx", "entity_id", "position"),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents_files.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registry_entities.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int]
    is_cover: Mapped[bool] = mapped_column(server_default=text("false"))

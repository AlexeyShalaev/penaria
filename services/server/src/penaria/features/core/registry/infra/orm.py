"""The registry's tables; every one is named registry_*."""

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import ARRAY, CheckConstraint, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from penaria.common.database import Base, Ltree


class EntityDB(Base):
    __tablename__ = "registry_entities"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('property', 'building', 'floor', 'space', 'container', 'item', 'device', 'system')",
            name="kind",
        ),
        CheckConstraint("status IN ('present', 'missing', 'lent', 'in_repair')", name="status"),
        CheckConstraint("privacy IN ('normal', 'guest_visible', 'private')", name="privacy"),
        CheckConstraint(
            "archive_reason IN ('discarded', 'sold', 'given_away', 'used_up', 'merged')", name="archive_reason"
        ),
        CheckConstraint("(parent_id IS NULL) = (kind = 'property')", name="root_is_property"),
        CheckConstraint("(archived_at IS NULL) = (archive_reason IS NULL)", name="archived_with_reason"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("registry_entities_path_idx", "path", postgresql_using="gist"),
        Index("registry_entities_home_id_parent_id_idx", "home_id", "parent_id"),
        Index(
            "registry_entities_home_id_verified_at_idx",
            "home_id",
            "verified_at",
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "registry_entities_name_trgm_idx",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_homes.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registry_entities.id"))
    path: Mapped[str] = mapped_column(Ltree)
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'present'"))
    privacy: Mapped[str] = mapped_column(Text, server_default=text("'normal'"))
    verified_at: Mapped[datetime.datetime | None]
    verified_by: Mapped[uuid.UUID | None]
    archived_at: Mapped[datetime.datetime | None]
    archive_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(server_default=text("1"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

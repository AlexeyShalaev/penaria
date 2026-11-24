"""The identity tables; every one is named identity_*."""

import datetime
import uuid

from sqlalchemy import ARRAY, CheckConstraint, ForeignKey, Index, Interval, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from penaria.common.database import Base


class Timestamps:
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserDB(Timestamps, Base):
    __tablename__ = "identity_users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)


class HomeDB(Timestamps, Base):
    __tablename__ = "identity_homes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)
    settings: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(server_default=text("1"))


class RoleDB(Timestamps, Base):
    __tablename__ = "identity_roles"
    __table_args__ = (
        CheckConstraint("preset IN ('owner', 'admin', 'family', 'guest', 'contractor')", name="preset"),
        CheckConstraint("preset IS NOT NULL OR name IS NOT NULL", name="named"),
        CheckConstraint("NOT expiry_required OR default_duration IS NOT NULL", name="expiry_duration"),
        Index("identity_roles_home_id_preset_key", "home_id", "preset", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_homes.id", ondelete="CASCADE"))
    preset: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    all_permissions: Mapped[bool] = mapped_column(server_default=text("false"))
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    guest_view: Mapped[bool] = mapped_column(server_default=text("false"))
    expiry_required: Mapped[bool] = mapped_column(server_default=text("false"))
    default_duration: Mapped[datetime.timedelta | None] = mapped_column(Interval)


class GrantDB(Base):
    __tablename__ = "identity_grants"
    __table_args__ = (
        CheckConstraint("principal_type IN ('user', 'device', 'link')", name="principal_type"),
        CheckConstraint("principal_type <> 'link' OR expires_at IS NOT NULL", name="link_expires"),
        Index("identity_grants_principal_idx", "principal_id", "home_id", postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_homes.id", ondelete="CASCADE"))
    principal_type: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[uuid.UUID]
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_roles.id"))
    # The registry's entities are the one cross-context reference grants keep (docs/design/core-model.md, 12).
    scope_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registry_entities.id"))
    expires_at: Mapped[datetime.datetime | None]
    revoked_at: Mapped[datetime.datetime | None]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

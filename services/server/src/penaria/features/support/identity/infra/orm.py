"""The identity tables; every one is named identity_*."""

import datetime
import uuid

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Interval,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from penaria.common.database import Base


class Timestamps:
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserDB(Timestamps, Base):
    __tablename__ = "identity_users"
    __table_args__ = (
        # Stored in lower case, so a plain unique index makes them unique case-insensitively.
        CheckConstraint("username = lower(username)", name="username_lower"),
        CheckConstraint("email = lower(email)", name="email_lower"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    install_admin: Mapped[bool] = mapped_column(server_default=text("false"))
    disabled_at: Mapped[datetime.datetime | None]


class PasswordDB(Base):
    __tablename__ = "identity_passwords"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True)
    hash: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime.datetime]


class SessionDB(Base):
    __tablename__ = "identity_sessions"
    __table_args__ = (Index("identity_sessions_user_id_idx", "user_id", postgresql_where=text("revoked_at IS NULL")),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime.datetime]
    last_seen_at: Mapped[datetime.datetime]
    authenticated_at: Mapped[datetime.datetime]
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    revoked_at: Mapped[datetime.datetime | None]


class PasskeyDB(Base):
    __tablename__ = "identity_passkeys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(Text)
    transports: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    created_at: Mapped[datetime.datetime]
    last_used_at: Mapped[datetime.datetime | None]


class PasskeyChallengeDB(Base):
    """Challenges given out for a passkey ceremony, each used at most once before it expires."""

    __tablename__ = "identity_passkey_challenges"
    __table_args__ = (
        CheckConstraint("ceremony IN ('registration', 'sign_in', 'reauthentication')", name="ceremony"),
        CheckConstraint("(ceremony = 'sign_in') = (session_id IS NULL)", name="session"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ceremony: Mapped[str] = mapped_column(Text)
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_sessions.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime.datetime] = mapped_column(index=True)


class SetupTokenDB(Base):
    """At most one row: the hash of the setup token printed at the last start before setup."""

    __tablename__ = "identity_setup_tokens"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    created_at: Mapped[datetime.datetime]


class SignInFailureDB(Base):
    __tablename__ = "identity_sign_in_failures"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    count: Mapped[int]
    last_at: Mapped[datetime.datetime] = mapped_column(index=True)


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

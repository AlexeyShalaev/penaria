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
    __table_args__ = (
        Index("identity_sessions_user_id_idx", "user_id", postgresql_where=text("revoked_at IS NULL")),
        Index("identity_sessions_grant_id_idx", "grant_id", postgresql_where=text("revoked_at IS NULL")),
        # An account's session, or a guest's of a guest link's grant (sign-in.md, 10).
        CheckConstraint("(user_id IS NULL) <> (grant_id IS NULL)", name="principal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_grants.id", ondelete="CASCADE"))
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
    # A sign-in's address, as its counter key (domain/throttle.py): the open ones per address are capped.
    address: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime.datetime] = mapped_column(index=True)


class TotpDB(Base):
    """An account's authenticator app (sign-in.md, 4.3): waiting for its first code until ``confirmed_at``."""

    __tablename__ = "identity_totp"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True)
    # The base32 secret, sealed with PENARIA_SECRET_KEY and bound to the account (domain/totp.py).
    secret: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime]
    confirmed_at: Mapped[datetime.datetime | None]
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    # SHA-256 hashes, in hex, of the recovery codes not used yet.
    recovery_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))


class PendingSignInDB(Base):
    """Sign-ins whose password was right and whose second factor is still to come; only their tokens' hashes."""

    __tablename__ = "identity_pending_sign_ins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"), index=True)
    # The counter key of the address the password came from (domain/throttle.py).
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime]
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
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id"))


class InvitationDB(Base):
    __tablename__ = "identity_invitations"
    __table_args__ = (
        Index(
            "identity_invitations_home_id_idx",
            "home_id",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        CheckConstraint("(accepted_at IS NULL) = (accepted_by IS NULL)", name="accepted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_homes.id", ondelete="CASCADE"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_roles.id"))
    scope_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registry_entities.id"))
    grant_expires_at: Mapped[datetime.datetime | None]
    leave_when_accepted: Mapped[bool] = mapped_column(server_default=text("false"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id"))
    created_at: Mapped[datetime.datetime]
    expires_at: Mapped[datetime.datetime]
    accepted_at: Mapped[datetime.datetime | None]
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id"))
    revoked_at: Mapped[datetime.datetime | None]


class TokenDB(Base):
    """Secrets that stand for a principal: the tokens of guest links and devices (sign-in.md, 10)."""

    __tablename__ = "identity_tokens"
    __table_args__ = (
        CheckConstraint("principal_type IN ('user', 'device', 'link')", name="principal_type"),
        Index("identity_tokens_principal_id_idx", "principal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    principal_type: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime]
    last_used_at: Mapped[datetime.datetime | None]
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    last_moved_at: Mapped[datetime.datetime | None]
    revoked_at: Mapped[datetime.datetime | None]


class InstallSettingDB(Base):
    """Settings of the install that its admins change in the interface; a secret goes sealed in ``secret``."""

    __tablename__ = "identity_install_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB)
    # Sealed with PENARIA_SECRET_KEY, bound to this table, column and key (domain/secrets.py).
    secret: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime]
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id", ondelete="SET NULL"))


class MailDB(Base):
    """Every email the install sends: the queue of those waiting and the log of the rest (sign-in.md, 15)."""

    __tablename__ = "identity_mail"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('test', 'email_verification', 'password_reset', 'invitation', 'password_changed', "
            "'passkey_added', 'email_changed', 'email_removed', 'totp_enabled', 'totp_disabled', "
            "'recovery_code_used', 'recovery_codes_regenerated')",
            name="kind",
        ),
        CheckConstraint("state IN ('queued', 'sent', 'failed')", name="state"),
        CheckConstraint("(state = 'queued') = (next_attempt_at IS NOT NULL)", name="queued"),
        Index("identity_mail_next_attempt_at_idx", "next_attempt_at", postgresql_where=text("state = 'queued'")),
        Index("identity_mail_expires_at_idx", "expires_at", postgresql_where=text("content IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    to_address: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id", ondelete="SET NULL"))
    locale: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    # The text and HTML, sealed: they carry links that open accounts. Cleared once it cannot be sent.
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime.datetime]
    state: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    next_attempt_at: Mapped[datetime.datetime | None]


class MailAttemptDB(Base):
    """One attempt to send a mail, and how it ended."""

    __tablename__ = "identity_mail_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    mail_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_mail.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime.datetime]
    duration_ms: Mapped[int]
    # None when it was sent.
    reason: Mapped[str | None] = mapped_column(Text)
    smtp_code: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime.datetime | None]
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id", ondelete="SET NULL"))


class AccountLinkDB(Base):
    """One-time links that reset a password or confirm an email; only their tokens' hashes."""

    __tablename__ = "identity_account_links"
    __table_args__ = (
        CheckConstraint("purpose IN ('password_reset', 'email_verification')", name="purpose"),
        CheckConstraint("(purpose = 'email_verification') = (email IS NOT NULL)", name="email"),
        Index("identity_account_links_user_id_idx", "user_id", postgresql_where=text("used_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime]
    expires_at: Mapped[datetime.datetime]
    used_at: Mapped[datetime.datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity_users.id", ondelete="SET NULL"))

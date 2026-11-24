"""Passkeys and the challenges of their ceremonies.

Revision ID: 818aae74a9af
Revises: f479701fbb82
Created: 2026-11-24 18:36:38.592354
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "818aae74a9af"
down_revision: str | None = "f479701fbb82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "identity_passkeys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("transports", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_passkeys_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_passkeys_pkey")),
        sa.UniqueConstraint("credential_id", name=op.f("identity_passkeys_credential_id_key")),
    )
    op.create_index(op.f("identity_passkeys_user_id_idx"), "identity_passkeys", ["user_id"], unique=False)
    op.create_table(
        "identity_passkey_challenges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ceremony", sa.Text(), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(ceremony = 'sign_in') = (session_id IS NULL)", name=op.f("identity_passkey_challenges_session_check")
        ),
        sa.CheckConstraint(
            "ceremony IN ('registration', 'sign_in', 'reauthentication')",
            name=op.f("identity_passkey_challenges_ceremony_check"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["identity_sessions.id"],
            name=op.f("identity_passkey_challenges_session_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_passkey_challenges_pkey")),
    )
    op.create_index(
        op.f("identity_passkey_challenges_expires_at_idx"), "identity_passkey_challenges", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(op.f("identity_passkey_challenges_expires_at_idx"), table_name="identity_passkey_challenges")
    op.drop_table("identity_passkey_challenges")
    op.drop_index(op.f("identity_passkeys_user_id_idx"), table_name="identity_passkeys")
    op.drop_table("identity_passkeys")

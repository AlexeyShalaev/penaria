"""The second factor: authenticator apps, sign-ins waiting for their code, and the emails that tell of them.

Revision ID: 790b3213f5d0
Revises: be404bf1ff55
Created: 2026-11-24 22:05:06.829389
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "790b3213f5d0"
down_revision: str | None = "be404bf1ff55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAIL_KINDS_BEFORE = (
    "kind IN ('test', 'email_verification', 'password_reset', 'invitation', 'password_changed', "
    "'passkey_added', 'email_changed', 'email_removed')"
)
MAIL_KINDS = (
    "kind IN ('test', 'email_verification', 'password_reset', 'invitation', 'password_changed', "
    "'passkey_added', 'email_changed', 'email_removed', 'totp_enabled', 'totp_disabled', "
    "'recovery_code_used', 'recovery_codes_regenerated')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "identity_pending_sign_ins",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_pending_sign_ins_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_pending_sign_ins_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("identity_pending_sign_ins_token_hash_key")),
    )
    op.create_index(
        op.f("identity_pending_sign_ins_expires_at_idx"), "identity_pending_sign_ins", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("identity_pending_sign_ins_user_id_idx"), "identity_pending_sign_ins", ["user_id"], unique=False
    )
    op.create_table(
        "identity_totp",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("confirmed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("recovery_codes", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_totp_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("identity_totp_pkey")),
    )
    op.drop_constraint(op.f("identity_mail_kind_check"), "identity_mail", type_="check")
    op.create_check_constraint(op.f("identity_mail_kind_check"), "identity_mail", MAIL_KINDS)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Authenticator apps are turned off, sign-ins waiting for their code fail, and the log forgets
    # the emails that told of the second factor (the old kinds cannot hold them).
    op.execute(
        "DELETE FROM identity_mail WHERE kind IN "
        "('totp_enabled', 'totp_disabled', 'recovery_code_used', 'recovery_codes_regenerated')"
    )
    op.drop_constraint(op.f("identity_mail_kind_check"), "identity_mail", type_="check")
    op.create_check_constraint(op.f("identity_mail_kind_check"), "identity_mail", MAIL_KINDS_BEFORE)
    op.drop_table("identity_totp")
    op.drop_index(op.f("identity_pending_sign_ins_user_id_idx"), table_name="identity_pending_sign_ins")
    op.drop_index(op.f("identity_pending_sign_ins_expires_at_idx"), table_name="identity_pending_sign_ins")
    op.drop_table("identity_pending_sign_ins")

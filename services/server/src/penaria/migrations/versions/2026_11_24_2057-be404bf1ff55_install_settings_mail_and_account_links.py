"""The install's settings, its mail queue and log, and one-time account links.

Revision ID: be404bf1ff55
Revises: 984ae8466901
Created: 2026-11-24 20:57:01.031602
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "be404bf1ff55"
down_revision: str | None = "984ae8466901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "identity_account_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "(purpose = 'email_verification') = (email IS NOT NULL)", name=op.f("identity_account_links_email_check")
        ),
        sa.CheckConstraint(
            "purpose IN ('password_reset', 'email_verification')", name=op.f("identity_account_links_purpose_check")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity_users.id"],
            name=op.f("identity_account_links_created_by_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_account_links_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_account_links_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("identity_account_links_token_hash_key")),
    )
    op.create_index(
        "identity_account_links_user_id_idx",
        "identity_account_links",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("used_at IS NULL"),
    )
    op.create_table(
        "identity_install_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity_users.id"],
            name=op.f("identity_install_settings_updated_by_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("identity_install_settings_pkey")),
    )
    op.create_table(
        "identity_mail",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retried", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "(state = 'queued') = (next_attempt_at IS NOT NULL)", name=op.f("identity_mail_queued_check")
        ),
        sa.CheckConstraint(
            "kind IN ('test', 'email_verification', 'password_reset', 'invitation', 'password_changed', "
            "'passkey_added')",
            name=op.f("identity_mail_kind_check"),
        ),
        sa.CheckConstraint("state IN ('queued', 'sent', 'failed')", name=op.f("identity_mail_state_check")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["identity_users.id"], name=op.f("identity_mail_created_by_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_mail_user_id_fkey"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_mail_pkey")),
    )
    op.create_index(op.f("identity_mail_created_at_idx"), "identity_mail", ["created_at"], unique=False)
    op.create_index(
        "identity_mail_expires_at_idx",
        "identity_mail",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("content IS NOT NULL"),
    )
    op.create_index(
        "identity_mail_next_attempt_at_idx",
        "identity_mail",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("state = 'queued'"),
    )
    op.create_table(
        "identity_mail_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("mail_id", sa.UUID(), nullable=False),
        sa.Column("at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("smtp_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["by"], ["identity_users.id"], name=op.f("identity_mail_attempts_by_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["mail_id"], ["identity_mail.id"], name=op.f("identity_mail_attempts_mail_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_mail_attempts_pkey")),
    )
    op.create_index(op.f("identity_mail_attempts_mail_id_idx"), "identity_mail_attempts", ["mail_id"], unique=False)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # The saved mailbox, the mail log and unused reset and confirmation links are lost.
    op.drop_index(op.f("identity_mail_attempts_mail_id_idx"), table_name="identity_mail_attempts")
    op.drop_table("identity_mail_attempts")
    op.drop_index(
        "identity_mail_next_attempt_at_idx", table_name="identity_mail", postgresql_where=sa.text("state = 'queued'")
    )
    op.drop_index(
        "identity_mail_expires_at_idx", table_name="identity_mail", postgresql_where=sa.text("content IS NOT NULL")
    )
    op.drop_index(op.f("identity_mail_created_at_idx"), table_name="identity_mail")
    op.drop_table("identity_mail")
    op.drop_table("identity_install_settings")
    op.drop_index(
        "identity_account_links_user_id_idx",
        table_name="identity_account_links",
        postgresql_where=sa.text("used_at IS NULL"),
    )
    op.drop_table("identity_account_links")

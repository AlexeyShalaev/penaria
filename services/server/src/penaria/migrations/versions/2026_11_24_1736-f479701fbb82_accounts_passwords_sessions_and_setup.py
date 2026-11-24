"""Accounts, passwords, sessions and the setup token.

Revision ID: f479701fbb82
Revises: 82f77ba98c6a
Created: 2026-11-24 17:36:48.751728
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f479701fbb82"
down_revision: str | None = "82f77ba98c6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("identity_users", sa.Column("username", sa.Text(), nullable=True))
    op.add_column("identity_users", sa.Column("email", sa.Text(), nullable=True))
    op.add_column(
        "identity_users", sa.Column("install_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("identity_users", sa.Column("disabled_at", postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.create_unique_constraint(op.f("identity_users_username_key"), "identity_users", ["username"])
    op.create_unique_constraint(op.f("identity_users_email_key"), "identity_users", ["email"])
    op.create_check_constraint(
        op.f("identity_users_username_lower_check"), "identity_users", "username = lower(username)"
    )
    op.create_check_constraint(op.f("identity_users_email_lower_check"), "identity_users", "email = lower(email)")
    # Events of an account, such as a sign-in, belong to no home.
    op.alter_column("journal_events", "home_id", existing_type=sa.UUID(), nullable=True)

    op.create_table(
        "identity_passwords",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("changed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_passwords_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("identity_passwords_pkey")),
    )
    op.create_table(
        "identity_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("authenticated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_sessions_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_sessions_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("identity_sessions_token_hash_key")),
    )
    op.create_index(
        "identity_sessions_user_id_idx",
        "identity_sessions",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "identity_setup_tokens",
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("identity_setup_tokens_pkey")),
    )
    op.create_table(
        "identity_sign_in_failures",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("last_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("identity_sign_in_failures_pkey")),
    )
    op.create_index(
        op.f("identity_sign_in_failures_last_at_idx"), "identity_sign_in_failures", ["last_at"], unique=False
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(op.f("identity_sign_in_failures_last_at_idx"), table_name="identity_sign_in_failures")
    op.drop_table("identity_sign_in_failures")
    op.drop_table("identity_setup_tokens")
    op.drop_index(
        "identity_sessions_user_id_idx", table_name="identity_sessions", postgresql_where=sa.text("revoked_at IS NULL")
    )
    op.drop_table("identity_sessions")
    op.drop_table("identity_passwords")
    # The account events have no home to go back to: going back drops them.
    op.execute("DELETE FROM journal_events WHERE home_id IS NULL")
    op.alter_column("journal_events", "home_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint(op.f("identity_users_email_lower_check"), "identity_users", type_="check")
    op.drop_constraint(op.f("identity_users_username_lower_check"), "identity_users", type_="check")
    op.drop_constraint(op.f("identity_users_email_key"), "identity_users", type_="unique")
    op.drop_constraint(op.f("identity_users_username_key"), "identity_users", type_="unique")
    op.drop_column("identity_users", "disabled_at")
    op.drop_column("identity_users", "install_admin")
    op.drop_column("identity_users", "email")
    op.drop_column("identity_users", "username")

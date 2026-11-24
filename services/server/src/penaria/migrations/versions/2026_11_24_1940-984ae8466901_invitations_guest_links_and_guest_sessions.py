"""Invitations, guest links and guest sessions.

Revision ID: 984ae8466901
Revises: 818aae74a9af
Created: 2026-11-24 19:40:03.437636
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "984ae8466901"
down_revision: str | None = "818aae74a9af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "identity_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("principal_type", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "principal_type IN ('user', 'device', 'link')", name=op.f("identity_tokens_principal_type_check")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_tokens_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("identity_tokens_token_hash_key")),
    )
    op.create_index("identity_tokens_principal_id_idx", "identity_tokens", ["principal_id"], unique=False)
    op.create_table(
        "identity_invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("home_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("scope_entity_id", sa.UUID(), nullable=True),
        sa.Column("grant_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("leave_when_accepted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("accepted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by IS NULL)", name=op.f("identity_invitations_accepted_check")
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by"], ["identity_users.id"], name=op.f("identity_invitations_accepted_by_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["identity_users.id"], name=op.f("identity_invitations_created_by_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["home_id"], ["identity_homes.id"], name=op.f("identity_invitations_home_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["identity_roles.id"], name=op.f("identity_invitations_role_id_fkey")),
        sa.ForeignKeyConstraint(
            ["scope_entity_id"], ["registry_entities.id"], name=op.f("identity_invitations_scope_entity_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_invitations_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("identity_invitations_token_hash_key")),
    )
    op.create_index(
        "identity_invitations_home_id_idx",
        "identity_invitations",
        ["home_id"],
        unique=False,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.add_column("identity_grants", sa.Column("granted_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("identity_grants_granted_by_fkey"), "identity_grants", "identity_users", ["granted_by"], ["id"]
    )
    op.add_column("identity_sessions", sa.Column("grant_id", sa.UUID(), nullable=True))
    op.alter_column("identity_sessions", "user_id", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint(
        op.f("identity_sessions_principal_check"), "identity_sessions", "(user_id IS NULL) <> (grant_id IS NULL)"
    )
    op.create_index(
        "identity_sessions_grant_id_idx",
        "identity_sessions",
        ["grant_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_foreign_key(
        op.f("identity_sessions_grant_id_fkey"),
        "identity_sessions",
        "identity_grants",
        ["grant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Guests' sessions have no account to keep them under, and guest links lose their tokens: they end.
    op.execute("DELETE FROM identity_sessions WHERE user_id IS NULL")
    op.execute("UPDATE identity_grants SET revoked_at = now() WHERE principal_type = 'link' AND revoked_at IS NULL")
    op.drop_constraint(op.f("identity_sessions_grant_id_fkey"), "identity_sessions", type_="foreignkey")
    op.drop_index(
        "identity_sessions_grant_id_idx", table_name="identity_sessions", postgresql_where=sa.text("revoked_at IS NULL")
    )
    op.drop_constraint(op.f("identity_sessions_principal_check"), "identity_sessions", type_="check")
    op.alter_column("identity_sessions", "user_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("identity_sessions", "grant_id")
    op.drop_constraint(op.f("identity_grants_granted_by_fkey"), "identity_grants", type_="foreignkey")
    op.drop_column("identity_grants", "granted_by")
    op.drop_index(
        "identity_invitations_home_id_idx",
        table_name="identity_invitations",
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_table("identity_invitations")
    op.drop_index("identity_tokens_principal_id_idx", table_name="identity_tokens")
    op.drop_table("identity_tokens")

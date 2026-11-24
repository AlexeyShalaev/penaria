"""Sign-in with the operator's OpenID Connect provider: linked identities, and flows waiting for the callback.

Revision ID: 3bf81f9554bf
Revises: 6a488348a488
Created: 2026-11-24 23:44:12.456208
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3bf81f9554bf"
down_revision: str | None = "6a488348a488"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "identity_external_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
            name=op.f("identity_external_identities_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_external_identities_pkey")),
    )
    op.create_index(
        "identity_external_identities_issuer_subject_key",
        "identity_external_identities",
        ["issuer", "subject"],
        unique=True,
    )
    op.create_index(
        "identity_external_identities_user_id_issuer_key",
        "identity_external_identities",
        ["user_id", "issuer"],
        unique=True,
    )
    op.create_table(
        "identity_oidc_flows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("state_hash", sa.LargeBinary(), nullable=False),
        sa.Column("browser_hash", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("return_to", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("invitation_hash", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(purpose = 'invitation') = (invitation_hash IS NOT NULL)",
            name=op.f("identity_oidc_flows_invitation_check"),
        ),
        sa.CheckConstraint(
            "(purpose IN ('link', 'reauthenticate')) = (session_id IS NOT NULL)",
            name=op.f("identity_oidc_flows_session_check"),
        ),
        sa.CheckConstraint(
            "purpose IN ('sign_in', 'link', 'reauthenticate', 'invitation')",
            name=op.f("identity_oidc_flows_purpose_check"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["identity_sessions.id"],
            name=op.f("identity_oidc_flows_session_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity_users.id"], name=op.f("identity_oidc_flows_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_oidc_flows_pkey")),
        sa.UniqueConstraint("state_hash", name=op.f("identity_oidc_flows_state_hash_key")),
    )
    op.create_index("identity_oidc_flows_address_idx", "identity_oidc_flows", ["address", "expires_at"], unique=False)
    op.create_index(op.f("identity_oidc_flows_expires_at_idx"), "identity_oidc_flows", ["expires_at"], unique=False)


def downgrade() -> None:
    # Forgets every linked identity: accounts made through the provider, which have no password, can then sign
    # in only after the operator's reset command (python -m penaria.apps.cli users reset).
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(op.f("identity_oidc_flows_expires_at_idx"), table_name="identity_oidc_flows")
    op.drop_index("identity_oidc_flows_address_idx", table_name="identity_oidc_flows")
    op.drop_table("identity_oidc_flows")
    op.drop_index("identity_external_identities_user_id_issuer_key", table_name="identity_external_identities")
    op.drop_index("identity_external_identities_issuer_subject_key", table_name="identity_external_identities")
    op.drop_table("identity_external_identities")

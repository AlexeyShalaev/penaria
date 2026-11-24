"""Identity, registry and journal tables.

Revision ID: 82f77ba98c6a
Revises: e0058541decd
Created: 2026-11-24 15:50:37.806978
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from penaria.common.database import Ltree, Xid8

revision: str = "82f77ba98c6a"
down_revision: str | None = "e0058541decd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_homes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_homes_pkey")),
    )
    op.create_table(
        "identity_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_users_pkey")),
    )
    op.create_table(
        "journal_events",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("home_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("actor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("command_id", sa.UUID(), nullable=True),
        sa.Column("changeset_id", sa.UUID(), nullable=True),
        sa.Column("tx", Xid8(), server_default=sa.text("pg_current_xact_id()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("seq", "at", name=op.f("journal_events_pkey")),
        postgresql_partition_by="RANGE (at)",
    )
    # Rows land in the default partition until monthly partitions are managed.
    op.execute("CREATE TABLE journal_events_default PARTITION OF journal_events DEFAULT")
    op.create_index("journal_events_entity_id_at_idx", "journal_events", ["entity_id", "at"], unique=False)
    op.create_index("journal_events_home_id_tx_seq_idx", "journal_events", ["home_id", "tx", "seq"], unique=False)
    op.create_index("journal_events_tx_seq_idx", "journal_events", ["tx", "seq"], unique=False)
    op.create_table(
        "identity_roles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("home_id", sa.UUID(), nullable=False),
        sa.Column("preset", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("all_permissions", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("permissions", sa.ARRAY(sa.String()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("guest_view", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expiry_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("default_duration", sa.Interval(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "preset IN ('owner', 'admin', 'family', 'guest', 'contractor')", name=op.f("identity_roles_preset_check")
        ),
        sa.CheckConstraint(
            "NOT expiry_required OR default_duration IS NOT NULL", name=op.f("identity_roles_expiry_duration_check")
        ),
        sa.CheckConstraint("preset IS NOT NULL OR name IS NOT NULL", name=op.f("identity_roles_named_check")),
        sa.ForeignKeyConstraint(
            ["home_id"], ["identity_homes.id"], name=op.f("identity_roles_home_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_roles_pkey")),
    )
    op.create_index("identity_roles_home_id_preset_key", "identity_roles", ["home_id", "preset"], unique=True)
    op.create_table(
        "registry_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("home_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("path", Ltree(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("aliases", sa.ARRAY(sa.String()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'present'"), nullable=False),
        sa.Column("privacy", sa.Text(), server_default=sa.text("'normal'"), nullable=False),
        sa.Column("verified_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("archived_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(parent_id IS NULL) = (kind = 'property')", name=op.f("registry_entities_root_is_property_check")
        ),
        sa.CheckConstraint(
            "archive_reason IN ('discarded', 'sold', 'given_away', 'used_up', 'merged')",
            name=op.f("registry_entities_archive_reason_check"),
        ),
        sa.CheckConstraint(
            "kind IN ('property', 'building', 'floor', 'space', 'container', 'item', 'device', 'system')",
            name=op.f("registry_entities_kind_check"),
        ),
        sa.CheckConstraint(
            "privacy IN ('normal', 'guest_visible', 'private')", name=op.f("registry_entities_privacy_check")
        ),
        sa.CheckConstraint(
            "status IN ('present', 'missing', 'lent', 'in_repair')", name=op.f("registry_entities_status_check")
        ),
        sa.CheckConstraint(
            "(archived_at IS NULL) = (archive_reason IS NULL)",
            name=op.f("registry_entities_archived_with_reason_check"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("registry_entities_quantity_positive_check")),
        sa.ForeignKeyConstraint(
            ["home_id"], ["identity_homes.id"], name=op.f("registry_entities_home_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["registry_entities.id"], name=op.f("registry_entities_parent_id_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("registry_entities_pkey")),
    )
    op.create_index(
        "registry_entities_home_id_parent_id_idx", "registry_entities", ["home_id", "parent_id"], unique=False
    )
    op.create_index(
        "registry_entities_home_id_verified_at_idx",
        "registry_entities",
        ["home_id", "verified_at"],
        unique=False,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "registry_entities_name_trgm_idx",
        "registry_entities",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index("registry_entities_path_idx", "registry_entities", ["path"], unique=False, postgresql_using="gist")
    op.create_table(
        "identity_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("home_id", sa.UUID(), nullable=False),
        sa.Column("principal_type", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("scope_entity_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "principal_type <> 'link' OR expires_at IS NOT NULL", name=op.f("identity_grants_link_expires_check")
        ),
        sa.CheckConstraint(
            "principal_type IN ('user', 'device', 'link')", name=op.f("identity_grants_principal_type_check")
        ),
        sa.ForeignKeyConstraint(
            ["home_id"], ["identity_homes.id"], name=op.f("identity_grants_home_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["identity_roles.id"], name=op.f("identity_grants_role_id_fkey")),
        sa.ForeignKeyConstraint(
            ["scope_entity_id"], ["registry_entities.id"], name=op.f("identity_grants_scope_entity_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("identity_grants_pkey")),
    )
    op.create_index(
        "identity_grants_principal_idx",
        "identity_grants",
        ["principal_id", "home_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "identity_grants_principal_idx", table_name="identity_grants", postgresql_where=sa.text("revoked_at IS NULL")
    )
    op.drop_table("identity_grants")
    op.drop_index("registry_entities_path_idx", table_name="registry_entities", postgresql_using="gist")
    op.drop_index(
        "registry_entities_name_trgm_idx",
        table_name="registry_entities",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "registry_entities_home_id_verified_at_idx",
        table_name="registry_entities",
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_index("registry_entities_home_id_parent_id_idx", table_name="registry_entities")
    op.drop_table("registry_entities")
    op.drop_index("identity_roles_home_id_preset_key", table_name="identity_roles")
    op.drop_table("identity_roles")
    op.drop_index("journal_events_tx_seq_idx", table_name="journal_events")
    op.drop_index("journal_events_home_id_tx_seq_idx", table_name="journal_events")
    op.drop_index("journal_events_entity_id_at_idx", table_name="journal_events")
    op.drop_table("journal_events")
    op.drop_table("identity_users")
    op.drop_table("identity_homes")

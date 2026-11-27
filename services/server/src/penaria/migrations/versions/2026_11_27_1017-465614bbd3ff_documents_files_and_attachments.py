"""Files of things and places: the files and which entities hold them.

Revision ID: 465614bbd3ff
Revises: 3bf81f9554bf
Created: 2026-11-27 10:17:37.292106
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "465614bbd3ff"
down_revision: str | None = "3bf81f9554bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "documents_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("home_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("taken_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("previews", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("added_by", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("removed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("leased_until", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "(status = 'failed') = (failure IS NOT NULL)", name=op.f("documents_files_failed_with_reason_check")
        ),
        sa.CheckConstraint(
            "kind IN ('photo', 'receipt', 'warranty', 'manual', 'other')", name=op.f("documents_files_kind_check")
        ),
        sa.CheckConstraint("status IN ('processing', 'ready', 'failed')", name=op.f("documents_files_status_check")),
        sa.CheckConstraint(
            "visibility IN ('normal', 'private', 'guests')", name=op.f("documents_files_visibility_check")
        ),
        sa.CheckConstraint("size >= 0", name=op.f("documents_files_size_not_negative_check")),
        sa.ForeignKeyConstraint(
            ["home_id"], ["identity_homes.id"], name=op.f("documents_files_home_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("documents_files_pkey")),
    )
    op.create_index(
        "documents_files_home_id_removed_at_idx",
        "documents_files",
        ["home_id", "removed_at"],
        unique=False,
        postgresql_where=sa.text("removed_at IS NOT NULL"),
    )
    op.create_index(
        "documents_files_queue_idx",
        "documents_files",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        "documents_files_removed_at_idx",
        "documents_files",
        ["removed_at"],
        unique=False,
        postgresql_where=sa.text("removed_at IS NOT NULL"),
    )
    op.create_table(
        "documents_attachments",
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_cover", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["registry_entities.id"],
            name=op.f("documents_attachments_entity_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["documents_files.id"], name=op.f("documents_attachments_file_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("file_id", "entity_id", name=op.f("documents_attachments_pkey")),
    )
    op.create_index(
        "documents_attachments_cover_key",
        "documents_attachments",
        ["entity_id"],
        unique=True,
        postgresql_where=sa.text("is_cover"),
    )
    op.create_index(
        "documents_attachments_entity_id_position_idx", "documents_attachments", ["entity_id", "position"], unique=False
    )


def downgrade() -> None:
    # Forgets every file: their objects stay in storage.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("documents_attachments_entity_id_position_idx", table_name="documents_attachments")
    op.drop_index(
        "documents_attachments_cover_key", table_name="documents_attachments", postgresql_where=sa.text("is_cover")
    )
    op.drop_table("documents_attachments")
    op.drop_index(
        "documents_files_removed_at_idx",
        table_name="documents_files",
        postgresql_where=sa.text("removed_at IS NOT NULL"),
    )
    op.drop_index(
        "documents_files_queue_idx", table_name="documents_files", postgresql_where=sa.text("status = 'processing'")
    )
    op.drop_index(
        "documents_files_home_id_removed_at_idx",
        table_name="documents_files",
        postgresql_where=sa.text("removed_at IS NOT NULL"),
    )
    op.drop_table("documents_files")

"""Extensions ltree and pg_trgm.

Revision ID: e0058541decd
Revises:
Created: 2026-11-24 15:22:19.123760
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e0058541decd"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ltree holds the entity tree's paths; pg_trgm matches names by similarity.
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # Extensions belong to the database, not to Penaria's schema: another schema may use
    # them, so a downgrade leaves them installed.
    pass

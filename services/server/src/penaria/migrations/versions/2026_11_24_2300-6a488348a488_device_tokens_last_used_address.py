"""Device tokens: the address a token was last used from.

Revision ID: 6a488348a488
Revises: 790b3213f5d0
Created: 2026-11-24 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6a488348a488"
down_revision: str | None = "790b3213f5d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("identity_tokens", sa.Column("last_used_ip", postgresql.INET(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("identity_tokens", "last_used_ip")

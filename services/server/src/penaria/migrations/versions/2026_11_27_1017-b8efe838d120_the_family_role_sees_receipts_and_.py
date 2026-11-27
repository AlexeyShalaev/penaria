"""The family role of the homes there are gets documents.view_financial, "See receipts and warranties".

Owner and admin hold every permission already; guest and contractor do not see them. Roles cannot be
edited or renamed yet, so every family role is the preset as it was made.

Revision ID: b8efe838d120
Revises: 465614bbd3ff
Created: 2026-11-27 10:17:50
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8efe838d120"
down_revision: str | None = "465614bbd3ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A few rows at most: a home has one family role.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "UPDATE identity_roles SET permissions = array_append(permissions, 'documents.view_financial')"
        " WHERE preset = 'family' AND NOT 'documents.view_financial' = ANY (permissions)"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "UPDATE identity_roles SET permissions = array_remove(permissions, 'documents.view_financial')"
        " WHERE preset = 'family'"
    )

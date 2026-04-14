"""add last_used to users

Revision ID: 7d7be8f7c0ee
Revises: 5ea6aea149ea
Create Date: 2026-03-03 12:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7d7be8f7c0ee"
down_revision: Union[str, Sequence[str], None] = "5ea6aea149ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("last_used", sa.String(length=16), nullable=False, server_default="professor"),
    )
    op.create_check_constraint(
        "ck_users_last_used",
        "users",
        "last_used IN ('professor', 'new')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_users_last_used", "users", type_="check")
    op.drop_column("users", "last_used")

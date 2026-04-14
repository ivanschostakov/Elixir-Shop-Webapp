"""rename thread_id to conversation_id

Revision ID: 5ea6aea149ea
Revises: d9d9bcd1a310
Create Date: 2026-02-27 16:39:08.777738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ea6aea149ea'
down_revision: Union[str, Sequence[str], None] = 'd9d9bcd1a310'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "users",
        "thread_id",
        existing_type=sa.String(),
        new_column_name="conversation_id",
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "users",
        "conversation_id",
        existing_type=sa.String(),
        new_column_name="thread_id",
        existing_nullable=True,
    )

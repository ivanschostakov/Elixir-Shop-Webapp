"""add source bot to user token usage

Revision ID: b1d7a4f2c3e9
Revises: 8c4e516d8b6a
Create Date: 2026-03-10 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1d7a4f2c3e9"
down_revision: Union[str, Sequence[str], None] = "8c4e516d8b6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("user_token_usage", sa.Column("source_bot", sa.String(length=64), nullable=True))
    op.create_index("ix_user_token_usage_source_bot", "user_token_usage", ["source_bot"], unique=False)

    op.execute(
        """
        UPDATE user_token_usage
        SET source_bot = CASE
            WHEN bot::text = 'new' THEN 'elixirpeptidebot'
            WHEN bot::text = 'dose' THEN 'peptideexpertbot'
            WHEN bot::text = 'professor' THEN 'professorofpeptidesbot'
            ELSE source_bot
        END
        WHERE source_bot IS NULL
          AND bot::text IN ('new', 'dose', 'professor')
        """
    )

    op.drop_constraint("uq_user_date_bot", "user_token_usage", type_="unique")
    op.create_unique_constraint("uq_user_date_bot_source", "user_token_usage", ["user_id", "date", "bot", "source_bot"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_user_date_bot_source", "user_token_usage", type_="unique")
    op.create_unique_constraint("uq_user_date_bot", "user_token_usage", ["user_id", "date", "bot"])
    op.drop_index("ix_user_token_usage_source_bot", table_name="user_token_usage")
    op.drop_column("user_token_usage", "source_bot")

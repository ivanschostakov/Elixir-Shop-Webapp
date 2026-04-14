"""backfill null user token usage counters

Revision ID: 8c4e516d8b6a
Revises: 2f3e4a5b6c7d
Create Date: 2026-03-10 09:25:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8c4e516d8b6a"
down_revision: Union[str, Sequence[str], None] = "2f3e4a5b6c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        UPDATE user_token_usage
        SET
            input_tokens = COALESCE(input_tokens, 0),
            cached_input_tokens = COALESCE(cached_input_tokens, 0),
            output_tokens = COALESCE(output_tokens, 0),
            total_requests = COALESCE(total_requests, 0)
        WHERE
            input_tokens IS NULL
            OR cached_input_tokens IS NULL
            OR output_tokens IS NULL
            OR total_requests IS NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Data backfill is irreversible.
    pass

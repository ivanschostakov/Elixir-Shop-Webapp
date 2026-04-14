"""add cached input tokens to user token usage

Revision ID: 2f3e4a5b6c7d
Revises: 7d7be8f7c0ee
Create Date: 2026-03-10 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2f3e4a5b6c7d"
down_revision: Union[str, Sequence[str], None] = "7d7be8f7c0ee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_token_usage",
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_token_usage",
        sa.Column("cached_input_tokens_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Historical rows do not contain exact cached token counts.
    # Backfill the best available estimate from the legacy request-count heuristic,
    # but keep that estimate explicit and auditable instead of baking it into pricing logic.
    op.execute(
        """
        UPDATE user_token_usage
        SET
            cached_input_tokens = LEAST(
                GREATEST(input_tokens, 0),
                ROUND(
                    GREATEST(input_tokens, 0) * CASE
                        WHEN bot::text = 'new' THEN LEAST(0.65, 0.25 + 0.08 * GREATEST(total_requests - 1, 0))
                        ELSE LEAST(0.45, 0.15 + 0.06 * GREATEST(total_requests - 1, 0))
                    END
                )::bigint
            ),
            cached_input_tokens_estimated = TRUE
        """
    )

    op.execute(
        """
        UPDATE user_token_usage
        SET
            input_cost_usd = ROUND(
                (
                    (
                        (GREATEST(input_tokens, 0) - cached_input_tokens)
                        * CASE WHEN bot::text = 'new' THEN 2.50 ELSE 0.25 END
                    )
                    + (
                        cached_input_tokens
                        * CASE WHEN bot::text = 'new' THEN 0.25 ELSE 0.025 END
                    )
                ) / 1000000.0,
                6
            ),
            output_cost_usd = ROUND(
                (
                    GREATEST(output_tokens, 0)
                    * CASE WHEN bot::text = 'new' THEN 15.00 ELSE 2.00 END
                ) / 1000000.0,
                6
            )
        """
    )

    op.alter_column("user_token_usage", "cached_input_tokens", server_default=None)
    op.alter_column("user_token_usage", "cached_input_tokens_estimated", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_token_usage", "cached_input_tokens_estimated")
    op.drop_column("user_token_usage", "cached_input_tokens")

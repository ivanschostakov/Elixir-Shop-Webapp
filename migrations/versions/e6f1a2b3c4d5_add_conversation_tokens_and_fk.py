"""add conversation tokens table and users conversation fk

Revision ID: e6f1a2b3c4d5
Revises: 4b2b8b0f5d34
Create Date: 2026-04-13 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "4b2b8b0f5d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_tokens",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(op.f("ix_conversation_tokens_created_at"), "conversation_tokens", ["created_at"], unique=False)

    # Keep FK values clean and backfill referenced rows for already existing users.
    op.execute(
        """
        UPDATE users
        SET conversation_id = btrim(conversation_id)
        WHERE conversation_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET conversation_id = NULL
        WHERE conversation_id IS NOT NULL
          AND btrim(conversation_id) = ''
        """
    )
    op.execute(
        """
        INSERT INTO conversation_tokens (conversation_id, input_tokens, cached_input_tokens, output_tokens)
        SELECT DISTINCT u.conversation_id, 0, 0, 0
        FROM users u
        WHERE u.conversation_id IS NOT NULL
        ON CONFLICT (conversation_id) DO NOTHING
        """
    )

    op.create_foreign_key(
        "fk_users_conversation_id_conversation_tokens",
        "users",
        "conversation_tokens",
        ["conversation_id"],
        ["conversation_id"],
        ondelete="SET NULL",
        onupdate="CASCADE",
    )

    op.alter_column("conversation_tokens", "input_tokens", server_default=None)
    op.alter_column("conversation_tokens", "cached_input_tokens", server_default=None)
    op.alter_column("conversation_tokens", "output_tokens", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_users_conversation_id_conversation_tokens", "users", type_="foreignkey")
    op.drop_index(op.f("ix_conversation_tokens_created_at"), table_name="conversation_tokens")
    op.drop_table("conversation_tokens")

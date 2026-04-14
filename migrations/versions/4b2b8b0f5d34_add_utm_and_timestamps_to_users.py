"""add utm attribution and timestamps to users

Revision ID: 4b2b8b0f5d34
Revises: c3d4e5f6a7b8
Create Date: 2026-04-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4b2b8b0f5d34"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("utm_source", sa.String(), nullable=True))
    op.add_column("users", sa.Column("utm_medium", sa.String(), nullable=True))
    op.add_column("users", sa.Column("utm_campaign", sa.String(), nullable=True))
    op.add_column("users", sa.Column("utm_content", sa.String(), nullable=True))
    op.add_column("users", sa.Column("utm_creative", sa.String(), nullable=True))
    op.add_column("users", sa.Column("utm_payload_raw", sa.String(), nullable=True))
    op.add_column("users", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))

    op.create_index(op.f("ix_users_utm_source"), "users", ["utm_source"], unique=False)
    op.create_index(op.f("ix_users_utm_medium"), "users", ["utm_medium"], unique=False)
    op.create_index(op.f("ix_users_utm_campaign"), "users", ["utm_campaign"], unique=False)
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_created_at"), table_name="users")
    op.drop_index(op.f("ix_users_utm_campaign"), table_name="users")
    op.drop_index(op.f("ix_users_utm_medium"), table_name="users")
    op.drop_index(op.f("ix_users_utm_source"), table_name="users")

    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
    op.drop_column("users", "utm_payload_raw")
    op.drop_column("users", "utm_creative")
    op.drop_column("users", "utm_content")
    op.drop_column("users", "utm_campaign")
    op.drop_column("users", "utm_medium")
    op.drop_column("users", "utm_source")

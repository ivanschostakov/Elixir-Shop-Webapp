"""add order fingerprint to carts

Revision ID: c3d4e5f6a7b8
Revises: 9c13c2a1b5ef
Create Date: 2026-03-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "9c13c2a1b5ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("carts", sa.Column("order_fingerprint", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_carts_active_order_fingerprint",
        "carts",
        ["order_fingerprint"],
        unique=True,
        postgresql_where=sa.text("order_fingerprint IS NOT NULL AND is_active = true AND is_canceled = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_carts_active_order_fingerprint", table_name="carts")
    op.drop_column("carts", "order_fingerprint")

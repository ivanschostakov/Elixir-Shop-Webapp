"""add moysklad order sync ids

Revision ID: f8a1b2c3d4e5
Revises: e6f1a2b3c4d5
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e6f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("moysklad_counterparty_id", sa.String(length=36), nullable=True))
    op.create_index("ix_users_moysklad_counterparty_id", "users", ["moysklad_counterparty_id"], unique=False)

    op.add_column("carts", sa.Column("moysklad_customerorder_id", sa.String(length=36), nullable=True))
    op.add_column("carts", sa.Column("moysklad_invoiceout_id", sa.String(length=36), nullable=True))
    op.create_index("ix_carts_moysklad_customerorder_id", "carts", ["moysklad_customerorder_id"], unique=False)
    op.create_index("ix_carts_moysklad_invoiceout_id", "carts", ["moysklad_invoiceout_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_carts_moysklad_invoiceout_id", table_name="carts")
    op.drop_index("ix_carts_moysklad_customerorder_id", table_name="carts")
    op.drop_column("carts", "moysklad_invoiceout_id")
    op.drop_column("carts", "moysklad_customerorder_id")

    op.drop_index("ix_users_moysklad_counterparty_id", table_name="users")
    op.drop_column("users", "moysklad_counterparty_id")

"""add contact id and payment tracking

Revision ID: 9c13c2a1b5ef
Revises: b1d7a4f2c3e9
Create Date: 2026-03-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c13c2a1b5ef"
down_revision: Union[str, Sequence[str], None] = "b1d7a4f2c3e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("contact_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_users_contact_id"), "users", ["contact_id"], unique=False)

    op.add_column("carts", sa.Column("payment_method", sa.String(), nullable=True))
    op.add_column("carts", sa.Column("payment_provider", sa.String(), nullable=True))
    op.add_column("carts", sa.Column("payment_status", sa.String(), nullable=True))
    op.add_column("carts", sa.Column("payment_invoice_id", sa.String(), nullable=True))
    op.add_column("carts", sa.Column("payment_paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("carts", sa.Column("payment_error", sa.String(), nullable=True))
    op.add_column("carts", sa.Column("amocrm_lead_id", sa.BigInteger(), nullable=True))
    op.add_column("carts", sa.Column("selected_delivery_service", sa.String(), nullable=True))
    op.add_column("carts", sa.Column("selected_delivery_payload", sa.JSON(), nullable=True))
    op.add_column("carts", sa.Column("checkout_snapshot", sa.JSON(), nullable=True))
    op.add_column("carts", sa.Column("delivery_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("carts", sa.Column("delivery_provider_ref", sa.String(), nullable=True))

    op.create_index(op.f("ix_carts_payment_status"), "carts", ["payment_status"], unique=False)
    op.create_index(op.f("ix_carts_payment_invoice_id"), "carts", ["payment_invoice_id"], unique=False)
    op.create_index(op.f("ix_carts_amocrm_lead_id"), "carts", ["amocrm_lead_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_carts_amocrm_lead_id"), table_name="carts")
    op.drop_index(op.f("ix_carts_payment_invoice_id"), table_name="carts")
    op.drop_index(op.f("ix_carts_payment_status"), table_name="carts")

    op.drop_column("carts", "delivery_provider_ref")
    op.drop_column("carts", "delivery_created_at")
    op.drop_column("carts", "checkout_snapshot")
    op.drop_column("carts", "selected_delivery_payload")
    op.drop_column("carts", "selected_delivery_service")
    op.drop_column("carts", "amocrm_lead_id")
    op.drop_column("carts", "payment_error")
    op.drop_column("carts", "payment_paid_at")
    op.drop_column("carts", "payment_invoice_id")
    op.drop_column("carts", "payment_status")
    op.drop_column("carts", "payment_provider")
    op.drop_column("carts", "payment_method")

    op.drop_index(op.f("ix_users_contact_id"), table_name="users")
    op.drop_column("users", "contact_id")

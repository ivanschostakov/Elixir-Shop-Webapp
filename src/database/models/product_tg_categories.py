from sqlalchemy import Column, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, Table

from src.database import Base

product_tg_categories = Table(
    "product_tg_categories",
    Base.metadata,
    Column("product_onec_id", String, ForeignKey("products.onec_id", ondelete="RESTRICT"), nullable=False),
    Column("tg_category_id", Integer, ForeignKey("tg_categories.id", ondelete="RESTRICT"), nullable=False),
    PrimaryKeyConstraint("product_onec_id", "tg_category_id", name="pk_product_tg_categories"),
    Index("ix_ptc_product_onec_id", "product_onec_id"),
    Index("ix_ptc_tg_category_id", "tg_category_id"),
)

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, index=True, nullable=False)
    cart_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    product_onec_id: Mapped[str] = mapped_column(String, ForeignKey("products.onec_id", ondelete="CASCADE"), nullable=False, index=True)
    feature_onec_id: Mapped[str] = mapped_column(String, ForeignKey("features.onec_id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    cart: Mapped["Cart"] = relationship("Cart", back_populates="items")
    product: Mapped["Product"] = relationship("Product", back_populates="cart_items", foreign_keys=[product_onec_id], lazy="selectin")
    feature: Mapped["Feature"] = relationship("Feature", back_populates="cart_items", foreign_keys=[feature_onec_id], lazy="selectin")

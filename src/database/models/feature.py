from decimal import Decimal
from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    onec_id: Mapped[str] = mapped_column(String, index=True, unique=True, nullable=False)
    product_onec_id: Mapped[str] = mapped_column(String, ForeignKey("products.onec_id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String, index=True, nullable=False)
    file_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped["Product"] = relationship("Product", back_populates="features")
    cart_items: Mapped[list["CartItem"]] = relationship("CartItem", back_populates="feature", foreign_keys="CartItem.feature_onec_id", lazy="selectin", passive_deletes=True)

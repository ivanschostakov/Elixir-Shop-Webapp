from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.database.models.product_tg_categories import product_tg_categories


class TgCategory(Base):
    __tablename__ = "tg_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    products: Mapped[list["Product"]] = relationship("Product", secondary=product_tg_categories, back_populates="tg_categories", lazy="selectin")

    def __repr__(self) -> str:
        return f"<TgCategory id={self.id} name={self.name!r}>"

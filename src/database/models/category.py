from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("onec_id", "unit_onec_id", name="uix_onec_unit"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    onec_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    unit_onec_id: Mapped[str | None] = mapped_column(String, ForeignKey("units.onec_id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str | None] = mapped_column(String, nullable=True)

    unit: Mapped["Unit"] = relationship("Unit", back_populates="categories")
    products: Mapped[list["Product"]] = relationship("Product", back_populates="category", cascade="all, delete-orphan")

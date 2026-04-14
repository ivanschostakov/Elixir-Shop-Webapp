from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.database.models.product_tg_categories import product_tg_categories


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    onec_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    usage: Mapped[str | None] = mapped_column(String, nullable=True)
    expiration: Mapped[str | None] = mapped_column(String, nullable=True)
    category_onec_id: Mapped[str | None] = mapped_column(String, ForeignKey("categories.onec_id", ondelete="SET NULL"), nullable=True, index=True)

    category: Mapped["Category"] = relationship("Category", back_populates="products")
    features: Mapped[list["Feature"]] = relationship("Feature", back_populates="product", cascade="all, delete-orphan")
    cart_items: Mapped[list["CartItem"]] = relationship("CartItem", back_populates="product", foreign_keys="CartItem.product_onec_id", lazy="selectin", passive_deletes=True)
    favourited_by: Mapped[list["Favourite"]] = relationship("Favourite", back_populates="product", cascade="all, delete-orphan")
    tg_categories: Mapped[list["TgCategory"]] = relationship("TgCategory", secondary=product_tg_categories, back_populates="products", lazy="selectin")

    def __str__(self) -> str:
        expiration_text = f"<b>ИНСТРУКЦИИ К ХРАНЕНИЮ</b>\n{self.expiration or 'Не имеются или <i>указаны выше</i>'}"
        usage_text = f"<b>ИНСТРУКЦИИ К ПРИММЕНЕНИЮ</b>\n{self.usage or 'Не имеются или <i>указаны выше</i>'}"
        description_text = f"<b>ОПИСАНИЕ</b>\n{self.description or 'Не имеется'}"
        prices_text = "\n".join([f"{feature.name} — {feature.price}₽" for feature in self.features])
        from src.helpers import normalize_html_for_telegram
        return normalize_html_for_telegram(
            f"<b>{self.name}</b>\n"
            f"Артикул: <i>{self.code}</i>\n"
            f"\n\n"
            f"{description_text}\n\n"
            f"{usage_text}\n\n"
            f"{expiration_text}\n\n"
            f"<b>ДОЗИРОВКИ И ЦЕНЫ:</b>\n"
            f"{prices_text}"
        )

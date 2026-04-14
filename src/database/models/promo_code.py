from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    __table_args__ = (
        CheckConstraint("times_used >= 0", name="ck_promo_times_used_nonneg"),
        CheckConstraint("owner_pct >= 0 AND owner_pct <= 100", name="ck_owner_pct_0_100"),
        CheckConstraint("lvl1_pct >= 0 AND lvl1_pct <= 100", name="ck_lvl1_pct_0_100"),
        CheckConstraint("lvl2_pct >= 0 AND lvl2_pct <= 100", name="ck_lvl2_pct_0_100"),
        CheckConstraint("owner_amount_gained >= 0", name="ck_owner_amount_nonneg"),
        CheckConstraint("lvl1_amount_gained >= 0", name="ck_lvl1_amount_nonneg"),
        CheckConstraint("lvl2_amount_gained >= 0", name="ck_lvl2_amount_nonneg"),
        Index("ix_promo_owner_levels", "owner_name", "lvl1_name", "lvl2_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    owner_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    owner_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    owner_amount_gained: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    lvl1_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    lvl1_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    lvl1_amount_gained: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    lvl2_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    lvl2_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    lvl2_amount_gained: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    times_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    carts: Mapped[list["Cart"]] = relationship("Cart", back_populates="promo", lazy="selectin", foreign_keys="Cart.promo_code")

    def __str__(self) -> str:
        return f"{self.code}: Скидка {self.discount_pct}"

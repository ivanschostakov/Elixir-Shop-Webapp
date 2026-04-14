import random

from decimal import Decimal
from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class UsedCode(Base):
    __tablename__ = "used_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_used_codes_code"), Index("ix_used_codes_user_id_code", "user_id", "code"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False, index=True, nullable=False, default=lambda: random.randint(10**6, 10**7 - 1))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String, nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

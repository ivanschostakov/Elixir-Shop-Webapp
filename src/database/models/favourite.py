from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Favourite(Base):
    __tablename__ = "favourites"
    __table_args__ = (UniqueConstraint("user_id", "onec_id", name="uq_favourites_user_product"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True, nullable=False)
    onec_id: Mapped[str] = mapped_column(String, ForeignKey("products.onec_id", ondelete="CASCADE"), index=True, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="favourites")
    product: Mapped["Product"] = relationship("Product", back_populates="favourited_by")

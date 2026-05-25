from datetime import datetime
from typing import Literal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Double, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("last_used IN ('professor', 'new')", name="ck_users_last_used"),)

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True, autoincrement=False)
    tg_ref_id: Mapped[int | None] = mapped_column(BigInteger, index=True, autoincrement=False, nullable=True, default=None)
    tg_phone: Mapped[str | None] = mapped_column(String, nullable=True, index=True, default=None)
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    contact_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None, index=True)
    moysklad_counterparty_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None, index=True)
    premium_requests: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    conversation_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("conversation_tokens.conversation_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
        default=None,
    )
    last_used: Mapped[Literal["professor", "new"]] = mapped_column(String(16), nullable=False, default="professor", server_default=text("'professor'"))
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    utm_source: Mapped[str | None] = mapped_column(String, nullable=True, default=None, index=True)
    utm_medium: Mapped[str | None] = mapped_column(String, nullable=True, default=None, index=True)
    utm_campaign: Mapped[str | None] = mapped_column(String, nullable=True, default=None, index=True)
    utm_content: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    utm_creative: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    utm_payload_raw: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    carts: Mapped[list["Cart"]] = relationship("Cart", back_populates="user", cascade="all, delete-orphan")
    favourites: Mapped[list["Favourite"]] = relationship("Favourite", back_populates="user", cascade="all, delete-orphan")
    token_usage: Mapped[list["UserTokenUsage"]] = relationship("UserTokenUsage", back_populates="user")
    conversation: Mapped["ConversationToken | None"] = relationship("ConversationToken", back_populates="users")

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LastUsedLiteral = Literal["professor", "new"]


class UserBase(BaseModel):
    tg_phone: str | None = Field(None, description="Telegram phone number of the user (if provided by Telegram)")
    photo_url: str | None = Field(None, description="User photo URL")
    contact_id: int | None = Field(None, description="amoCRM contact ID")
    moysklad_counterparty_id: str | None = Field(None, description="MoySklad counterparty ID")
    conversation_id: str | None = Field(None, description="Associated OpenAI conversation ID")
    premium_requests: float = Field(0, ge=0, description="How many premium model requests the user has")
    premium_until: datetime | None = Field(None, description="Updated premium until")
    input_tokens: int = Field(0, ge=0, description="Total number of input tokens used by the user")
    output_tokens: int = Field(0, ge=0, description="Total number of output tokens used by the user")
    blocked_until: datetime | None = Field(None, description="User blocked until this datetime")
    last_used: LastUsedLiteral = Field("professor", description="Last selected bot mode")
    utm_source: str | None = Field(None, description="First-touch UTM source")
    utm_medium: str | None = Field(None, description="First-touch UTM medium")
    utm_campaign: str | None = Field(None, description="First-touch UTM campaign")
    utm_content: str | None = Field(None, description="First-touch UTM content")
    utm_creative: str | None = Field(None, description="First-touch UTM creative")
    utm_payload_raw: str | None = Field(None, description="Decoded /start payload captured on first touch")

class UserCreate(UserBase):
    """Schema used when creating a new user."""
    tg_id: int = Field(..., description="Telegram user ID")
    tg_ref_id: int | None = Field(None, description="Optional referral user ID")

class UserUpdate(BaseModel):
    """Schema used when updating existing user fields."""
    tg_phone: str | None = None
    photo_url: str | None = None
    contact_id: int | None = None
    moysklad_counterparty_id: str | None = None
    conversation_id: str | None = None
    premium_requests: float | None = Field(None, description="Updated premium requests counter")
    premium_until: datetime | None = Field(None, description="Updated premium until")
    input_tokens: int | None = None
    output_tokens: int | None = None
    blocked_until: datetime | None = None
    tg_ref_id: int | None = None
    last_used: LastUsedLiteral | None = None

class UserRead(UserBase):
    tg_id: int
    tg_ref_id: int | None = None
    created_at: datetime
    updated_at: datetime

    class Config: orm_mode = True

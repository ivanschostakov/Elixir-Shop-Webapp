from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.database.schemas.cart_item import CartItemRead

ZERO_MONEY = Decimal("0.00")

class PromoCodeRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    owner_name: str
    owner_pct: Decimal

    lvl1_name: str | None = None
    lvl1_pct: Decimal

    lvl2_name: str | None = None
    lvl2_pct: Decimal

class CartCreate(BaseModel):
    user_id: int
    phone: str
    email: str

    name: str | None = None

    sum: Decimal = Field(default=ZERO_MONEY)
    delivery_sum: Decimal = Field(default=ZERO_MONEY)

    promo_code: str | None = None
    promo_gains: Decimal = Field(default=ZERO_MONEY)
    promo_gains_given: bool = False

    delivery_string: str = "Не указан"
    commentary: str | None = None
    payment_method: str | None = None
    payment_provider: str | None = None
    payment_status: str | None = None
    payment_invoice_id: str | None = None
    payment_paid_at: datetime | None = None
    payment_error: str | None = None
    amocrm_lead_id: int | None = None
    order_fingerprint: str | None = None
    selected_delivery_service: str | None = None
    selected_delivery_payload: dict[str, Any] | None = None
    checkout_snapshot: dict[str, Any] | None = None
    delivery_created_at: datetime | None = None
    delivery_provider_ref: str | None = None

    is_active: bool = True
    is_paid: bool = False
    is_canceled: bool = False
    is_shipped: bool = False

    status: str | None = None
    yandex_request_id: str | None = None

    @field_validator("sum", "delivery_sum", "promo_gains", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        if v is None or v == "": return ZERO_MONEY
        return Decimal(str(v).replace(",", "."))

class CartUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None

    sum: Decimal | None = None
    delivery_sum: Decimal | None = None

    promo_code: str | None = None
    promo_gains: Decimal | None = None
    promo_gains_given: bool | None = None

    delivery_string: str | None = None
    commentary: str | None = None
    payment_method: str | None = None
    payment_provider: str | None = None
    payment_status: str | None = None
    payment_invoice_id: str | None = None
    payment_paid_at: datetime | None = None
    payment_error: str | None = None
    amocrm_lead_id: int | None = None
    order_fingerprint: str | None = None
    selected_delivery_service: str | None = None
    selected_delivery_payload: dict[str, Any] | None = None
    checkout_snapshot: dict[str, Any] | None = None
    delivery_created_at: datetime | None = None
    delivery_provider_ref: str | None = None

    is_active: bool | None = None
    is_paid: bool | None = None
    is_canceled: bool | None = None
    is_shipped: bool | None = None

    status: str | None = None
    yandex_request_id: str | None = None

class CartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    phone: str
    email: str

    name: str | None = None

    sum: Decimal
    delivery_sum: Decimal

    promo_code: str | None = None
    promo_gains: Decimal
    promo_gains_given: bool

    promo: PromoCodeRef | None = None

    delivery_string: str
    commentary: str | None = None
    payment_method: str | None = None
    payment_provider: str | None = None
    payment_status: str | None = None
    payment_invoice_id: str | None = None
    payment_paid_at: datetime | None = None
    payment_error: str | None = None
    amocrm_lead_id: int | None = None
    order_fingerprint: str | None = None
    selected_delivery_service: str | None = None
    selected_delivery_payload: dict[str, Any] | None = None
    checkout_snapshot: dict[str, Any] | None = None
    delivery_created_at: datetime | None = None
    delivery_provider_ref: str | None = None

    is_active: bool
    is_paid: bool
    is_canceled: bool
    is_shipped: bool

    status: str | None = None
    yandex_request_id: str | None = None

    created_at: datetime
    updated_at: datetime

    items: list[CartItemRead] = Field(default_factory=list)

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TgCategoryMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ProductMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    onec_id: str
    name: str
    code: str
    tg_categories: list[TgCategoryMini] = Field(default_factory=list)


class FeatureMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    onec_id: str
    name: str
    code: str
    price: float


class CartItemWebRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cart_id: int
    product_onec_id: str
    feature_onec_id: str
    quantity: int
    created_at: datetime
    updated_at: datetime
    product: ProductMini | None = None
    feature: FeatureMini | None = None


class CartWebRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    user_id: int
    status: str | None = None
    sum: float
    delivery_sum: float
    delivery_string: str
    commentary: str | None = None
    payment_method: str | None = None
    payment_status: str | None = None
    phone: str
    email: str
    is_active: bool
    is_paid: bool
    is_canceled: bool
    is_shipped: bool
    created_at: datetime
    updated_at: datetime
    items: list[CartItemWebRead] = Field(default_factory=list)

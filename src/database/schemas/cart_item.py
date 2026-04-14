from datetime import datetime

from pydantic import BaseModel, ConfigDict

class CartItemBase(BaseModel):
    product_onec_id: str
    feature_onec_id: str
    quantity: int

class CartItemCreate(CartItemBase):
    pass

class CartItemUpdate(BaseModel):
    quantity: int | None = None

class CartItemRead(CartItemBase):
    id: int
    cart_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
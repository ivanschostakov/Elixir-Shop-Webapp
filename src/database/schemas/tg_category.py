from datetime import datetime
from pydantic import BaseModel

class TgCategoryBase(BaseModel):
    name: str
    description: str | None = None

class TgCategoryCreate(TgCategoryBase): pass
class TgCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class TgCategoryRead(TgCategoryBase):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    product_count: int | None = None
    class Config: from_attributes = True
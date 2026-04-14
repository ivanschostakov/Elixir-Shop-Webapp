from pydantic import BaseModel
from src.database.schemas.tg_category import TgCategoryRead

class ProductBase(BaseModel):
    onec_id: str
    category_onec_id: str
    name: str
    code: str
    description: str | None = None
    usage: str | None = None
    expiration: str | None = None

class ProductCreate(ProductBase): pass
class ProductUpdate(BaseModel):
    onec_id: str | None = None
    category_onec_id: str | None = None
    name: str | None = None
    code: str | None = None
    description: str | None = None
    usage: str | None = None
    expiration: str | None = None
    tg_category_ids: list[int] | None = None

class ProductRead(ProductBase):
    id: int
    tg_categories: list[TgCategoryRead] = []
    class Config: from_attributes = True
from pydantic import BaseModel

class CategoryBase(BaseModel):
    onec_id: str
    unit_onec_id: str | None = None
    name: str
    code: str | None = None            

class CategoryCreate(CategoryBase): pass
class CategoryUpdate(CategoryBase):
    onec_id: str | None = None
    unit_onec_id: str | None = None
    name: str | None = None
    code: str | None = None

class CategoryRead(CategoryBase):
    id: int
    class Config: from_attributes = True

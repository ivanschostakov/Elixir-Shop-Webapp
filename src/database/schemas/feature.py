from pydantic import BaseModel

class FeatureBase(BaseModel):
    onec_id: str
    product_onec_id: str
    name: str
    code: str
    file_id: str
    price: float = 0
    balance: int = 0

class FeatureCreate(FeatureBase): pass

class FeatureUpdate(BaseModel):
    onec_id: str | None = None
    product_onec_id: str | None = None
    name: str | None = None
    code: str | None = None
    file_id: str | None = None
    price: float | None = None
    balance: int | None = None

class FeatureRead(FeatureBase):
    id: int

    class Config: from_attributes = True

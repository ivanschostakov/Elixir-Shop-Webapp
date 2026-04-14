from pydantic import BaseModel

class UnitBase(BaseModel):
    onec_id: str
    name: str
    description: str

class UnitCreate(UnitBase): pass
class UnitUpdate(BaseModel):
    onec_id: str | None = None
    name: str | None = None
    description: str | None = None

class UnitRead(UnitBase):
    id: int
    class Config: from_attributes = True

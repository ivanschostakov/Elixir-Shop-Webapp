from pydantic import BaseModel, ConfigDict
from decimal import Decimal

class UsedCodeBase(BaseModel):
    user_id: int
    code: str
    price: Decimal                                 

class UsedCodeCreate(UsedCodeBase): pass
class UsedCodeUpdate(BaseModel):
    code: str | None = None
    price: Decimal | None = None

class UsedCodeRead(UsedCodeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
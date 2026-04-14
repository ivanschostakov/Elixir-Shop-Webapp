from datetime import date
from typing import Literal

from pydantic import BaseModel

BotLiteral = Literal["dose", "professor", "new"]

class UserTokenUsageBase(BaseModel):
    user_id: int
    date: date
    bot: BotLiteral
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    total_requests: int = 0           

class UserTokenUsageCreate(UserTokenUsageBase):
    pass

class UserTokenUsageUpdate(BaseModel):
    bot: BotLiteral | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    total_requests: int | None = None          

class UserTokenUsageRead(UserTokenUsageBase):
    id: int
    cached_input_tokens_estimated: bool
    input_cost_usd: float
    output_cost_usd: float

    class Config:
        from_attributes = True

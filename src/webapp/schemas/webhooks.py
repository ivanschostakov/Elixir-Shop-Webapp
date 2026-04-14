from typing import Literal

from pydantic import BaseModel, Field

PriceT = int | None | Literal["old", "not_found", "low"]


class VerifyOrderIn(BaseModel):
    code: str | int = Field(..., description="Код заказа/сделки, который ищем в amoCRM (№{code} )")


class VerifyOrderOut(BaseModel):
    status: Literal["ok", "not_found", "no_email", "smtp_failed", "low"]
    price: PriceT
    email: str | None = None
    verification_code: str | None = None

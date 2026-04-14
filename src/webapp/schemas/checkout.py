from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


async def enrich_cart_items(items: list[dict], db: AsyncSession) -> dict:
    from src.database.models import Feature

    if not items:
        return {"items": [], "total": 0}

    feature_ids = [item["featureId"] for item in items if item.get("featureId")]
    feature_map = {}

    if feature_ids:
        result = await db.execute(select(Feature).where(Feature.onec_id.in_(feature_ids)))
        features = result.scalars().all()
        feature_map = {f.onec_id: f for f in features}

    enriched = []
    total = Decimal(0)

    for item in items:
        pid = item.get("id")
        fid = item.get("featureId")
        qty = item.get("qty", 1)

        feature = feature_map.get(fid)
        if feature:
            price = Decimal(feature.price)
            subtotal = price * qty
            total += subtotal

            enriched.append(
                {
                    "id": pid,
                    "featureId": fid,
                    "name": feature.name,
                    "price": float(price),
                    "qty": qty,
                    "subtotal": float(subtotal),
                }
            )

    return {"items": enriched, "total": float(total)}


def build_receipt(enriched_cart: dict, delivery_sum: Decimal = Decimal("0.00")):
    items = enriched_cart.get("items", [])
    receipt_items = []

    for item in items:
        price = Decimal(str(item.get("price", 0)))
        qty = Decimal(str(item.get("qty", 1)))
        receipt_items.append(
            {
                "description": str(item.get("name") or item.get("id") or "Товар"),
                "quantity": f"{qty:.3f}",
                "amount": {"value": f"{price:.2f}", "currency": "RUB"},
                "vat_code": 2,
                "payment_mode": "full_prepayment",
                "payment_subject": "commodity",
            }
        )

    if delivery_sum and delivery_sum > 0:
        receipt_items.append(
            {
                "description": "Доставка",
                "quantity": "1.000",
                "amount": {"value": f"{delivery_sum:.2f}", "currency": "RUB"},
                "vat_code": 2,
                "payment_mode": "full_prepayment",
                "payment_subject": "service",
            }
        )

    return {"items": receipt_items, "tax_system_code": 1}


class ContactInfo(BaseModel):
    name: str = Field(..., example="Paylak")
    surname: str = Field(..., example="Urusyan")
    phone: str = Field(..., example="+17632730385")
    email: EmailStr = Field(..., example="urusy001@umn.edu")


class CheckoutData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    tg_nick: str | None = None
    checkout_data: dict[str, Any]
    selected_delivery: dict[str, Any]
    selected_delivery_service: str
    contact_info: ContactInfo | None = None
    source: str | None = None
    payment_method: str | None = None
    promocode: str | None = None
    commentary: str | None = None

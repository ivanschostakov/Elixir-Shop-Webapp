from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, HTTPException, Query, Depends, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.crud import get_feature, create_cart, get_user_carts_webapp, get_promo_by_code
from src.database import get_db
from src.database.models import Feature, Product
from src.database.schemas import CartCreate
from src.webapp.schemas import CartWebRead

router = APIRouter(prefix="/cart", tags=["cart"])
Q2 = Decimal("0.01")
D100 = Decimal("100")
NON_DISCOUNTABLE_TG_CATEGORY_IDS = frozenset({17})


def _is_discount_exempt_product(product: Product | None) -> bool:
    tg_categories = getattr(product, "tg_categories", None) or []
    return any(category.id in NON_DISCOUNTABLE_TG_CATEGORY_IDS for category in tg_categories)


@router.get("/", response_model=list[CartWebRead])
async def get_orders(user_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    carts = await get_user_carts_webapp(db, user_id)
    carts = [c for c in carts if 'ачальная' not in (c.name or "")]
    return carts


@router.get("/product/{onec_id}")
async def get_cart_product(onec_id: str, feature_id: str = Query("", alias="feature_id"), db: AsyncSession = Depends(get_db)):
    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.tg_categories))
            .where(Product.onec_id == onec_id)
        )
    ).scalars().first()
    if not product: raise HTTPException(status_code=404, detail="Product not found")

    feature = None
    if feature_id:
        feature = await get_feature(db, 'onec_id', feature_id)
        if not feature: raise HTTPException(status_code=404, detail="Feature not found")

    product_data = product.to_dict()
    product_data["tg_category_ids"] = [category.id for category in (getattr(product, "tg_categories", None) or [])]
    return {"product": product_data, "feature": feature.to_dict() if feature else None}


@router.post("/create")
async def create(cart_data: CartCreate, db: AsyncSession = Depends(get_db)):
    cart = await create_cart(db, cart_data)
    return cart.to_dict()


@router.post("/json")
async def cart_json(cart_data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """
    Receives the current cart from frontend and returns
    enriched data (features, totals).
    """

    items = cart_data.get("items", [])
    if not items:
        return {
            "items": [],
            "raw_total": 0,
            "discount_exempt_total": 0,
            "discountable_total": 0,
            "applied_discount_pct": 0,
            "discount_amount": 0,
            "total": 0,
        }

                                        
    feature_ids = [item["featureId"] for item in items if item.get("featureId")]
    feature_map = {}

    if feature_ids:
        result = await db.execute(
            select(Feature)
            .options(selectinload(Feature.product).selectinload(Product.tg_categories))
            .where(Feature.onec_id.in_(feature_ids))
        )
        features = result.scalars().all()
        feature_map = {f.onec_id: f for f in features}

    enriched = []
    raw_total = Decimal(0)
    discount_exempt_total = Decimal(0)

    for item in items:
        pid = item.get("id")

        fid = item.get("featureId")
        qty = item.get("qty", 1)

        feature: Feature = feature_map.get(fid)
        if feature:
            price = Decimal(feature.price)
            subtotal = price * qty
            raw_total += subtotal
            raw_name = str(item.get("name") or "").strip()
            if raw_name.lower() in {"none", "null"}:
                raw_name = ""
            product_name = (getattr(feature.product, "name", None) or "").strip()
            feature_name = (feature.name or "").strip()
            resolved_name = raw_name or product_name or feature_name or "Товар"
            is_discount_exempt = _is_discount_exempt_product(feature.product)
            if is_discount_exempt:
                discount_exempt_total += subtotal
            enriched.append({
                "id": pid,
                "name": resolved_name,
                "product_name": product_name or None,
                "feature_name": feature_name or None,
                "featureId": fid,
                "price": float(price),
                "qty": qty,
                "subtotal": float(subtotal),
                "is_discount_exempt": is_discount_exempt,
                "tg_category_ids": [
                    category.id for category in (getattr(feature.product, "tg_categories", None) or [])
                ],
            })

    discountable_total = raw_total - discount_exempt_total
    promo_code_raw = str(cart_data.get("promo_code") or "").strip()
    promo = await get_promo_by_code(db, promo_code_raw) if promo_code_raw else None
    applied_discount_pct = Decimal(str(promo.discount_pct or 0)) if promo else Decimal("0")
    discount_amount = Decimal("0.00")
    total = raw_total.quantize(Q2, rounding=ROUND_HALF_UP)

    if applied_discount_pct > 0 and discountable_total > 0:
        discounted_discountable_total = (
            discountable_total * (D100 - applied_discount_pct) / D100
        ).quantize(Q2, rounding=ROUND_HALF_UP)
        discount_amount = (discountable_total - discounted_discountable_total).quantize(Q2, rounding=ROUND_HALF_UP)
        total = (discount_exempt_total + discounted_discountable_total).quantize(Q2, rounding=ROUND_HALF_UP)

    return {
        "items": enriched,
        "raw_total": float(raw_total.quantize(Q2, rounding=ROUND_HALF_UP)),
        "discount_exempt_total": float(discount_exempt_total.quantize(Q2, rounding=ROUND_HALF_UP)),
        "discountable_total": float(discountable_total.quantize(Q2, rounding=ROUND_HALF_UP)),
        "applied_discount_pct": float(applied_discount_pct),
        "discount_amount": float(discount_amount),
        "total": float(total),
    }

from decimal import Decimal
from fastapi import APIRouter, HTTPException, Query, Depends, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.crud import get_product, get_feature, create_cart, get_user_carts_webapp
from src.database import get_db
from src.database.models import Feature
from src.database.schemas import CartCreate
from src.webapp.schemas import CartWebRead

router = APIRouter(prefix="/cart", tags=["cart"])

@router.get("/", response_model=list[CartWebRead])
async def get_orders(user_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    carts = await get_user_carts_webapp(db, user_id)
    carts = [c for c in carts if 'ачальная' not in (c.name or "")]
    return carts

@router.get("/product/{onec_id}")
async def get_cart_product(onec_id: str, feature_id: str = Query("", alias="feature_id"), db: AsyncSession = Depends(get_db)):
    product = await get_product(db, 'onec_id', onec_id)
    if not product: raise HTTPException(status_code=404, detail="Product not found")

    feature = None
    if feature_id:
        feature = await get_feature(db, 'onec_id', feature_id)
        if not feature: raise HTTPException(status_code=404, detail="Feature not found")

    return {"product": product.to_dict(), "feature": feature.to_dict()}

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
    if not items: return {"items": [], "total": 0}

                                        
    feature_ids = [item["featureId"] for item in items if item.get("featureId")]
    feature_map = {}

    if feature_ids:
        result = await db.execute(select(Feature).options(selectinload(Feature.product)).where(Feature.onec_id.in_(feature_ids)))
        features = result.scalars().all()
        feature_map = {f.onec_id: f for f in features}

    enriched = []
    total = Decimal(0)

    for item in items:
        pid = item.get("id")

        fid = item.get("featureId")
        qty = item.get("qty", 1)

        feature: Feature = feature_map.get(fid)
        if feature:
            price = Decimal(feature.price)
            subtotal = price * qty
            total += subtotal
            raw_name = str(item.get("name") or "").strip()
            if raw_name.lower() in {"none", "null"}:
                raw_name = ""
            product_name = (getattr(feature.product, "name", None) or "").strip()
            feature_name = (feature.name or "").strip()
            resolved_name = raw_name or product_name or feature_name or "Товар"
            enriched.append({
                "id": pid,
                "name": resolved_name,
                "product_name": product_name or None,
                "feature_name": feature_name or None,
                "featureId": fid,
                "price": float(price),
                "qty": qty,
                "subtotal": float(subtotal)
            })

    return {"items": enriched, "total": float(total)}

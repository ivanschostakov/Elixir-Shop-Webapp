from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, Query, HTTPException

from src.database.crud import get_promo_by_code, update_promo
from src.database import get_db
from src.database.schemas import PromoCodeOut, PromoCodeUpdate

router = APIRouter(prefix="/promocodes", tags=["promocodes"])

Q2 = Decimal("0.01")
D100 = Decimal("100")

@router.get("/", response_model=PromoCodeOut)
async def promocodes_get(code: str = Query(...), db=Depends(get_db)):
    promo_code = await get_promo_by_code(db, code.strip())
    if not promo_code: raise HTTPException(status_code=404, detail="Promo code not found")
    return promo_code

@router.post("/calculate-price")
async def calculate_price(code: str = Query(...), init_price: Decimal = Query(...), db=Depends(get_db)):
    promo_code = await get_promo_by_code(db, code.strip())
    if not promo_code: raise HTTPException(status_code=404, detail="Promo code not found")
    if init_price <= 0: raise HTTPException(status_code=400, detail="Price must be greater than 0")

    discount_pct = Decimal(promo_code.discount_pct or 0)
    owner_pct = Decimal(promo_code.owner_pct or 0)
    lvl1_pct = Decimal(promo_code.lvl1_pct or 0)
    lvl2_pct = Decimal(promo_code.lvl2_pct or 0)

    result_price = (init_price * (D100 - discount_pct) / D100).quantize(Q2, rounding=ROUND_HALF_UP)

    new_owner_gained = (Decimal(promo_code.owner_amount_gained or 0) + (result_price * owner_pct / D100)).quantize(Q2, rounding=ROUND_HALF_UP)
    new_lvl1_gained  = (Decimal(promo_code.lvl1_amount_gained  or 0) + (result_price * lvl1_pct  / D100)).quantize(Q2, rounding=ROUND_HALF_UP)
    new_lvl2_gained  = (Decimal(promo_code.lvl2_amount_gained  or 0) + (result_price * lvl2_pct  / D100)).quantize(Q2, rounding=ROUND_HALF_UP)

    promo_code_update = PromoCodeUpdate(owner_amount_gained=new_owner_gained, lvl1_amount_gained=new_lvl1_gained, lvl2_amount_gained=new_lvl2_gained, times_used=(promo_code.times_used or 0) + 1)

    await update_promo(db, promo_code.id, promo_code_update)
    return {"result_price": result_price}

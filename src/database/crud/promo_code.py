from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.promo_code import PromoCode
from src.database.schemas.promo_code import PromoCodeCreate, PromoCodeUpdate

async def get_promo_by_id(db: AsyncSession, promo_id: int) -> PromoCode | None:
    res = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    return res.scalar_one_or_none()

async def get_promo_by_code(db: AsyncSession, code: str) -> PromoCode | None:
    code = (code or "").strip()
    if not code: return None
    res = await db.execute(select(PromoCode).where(PromoCode.code == code))
    return res.scalar_one_or_none()

async def list_promos(db: AsyncSession):
    stmt = select(PromoCode)
    res = await db.execute(stmt)
    return res.scalars().all()

async def create_promo(db: AsyncSession, data: PromoCodeCreate) -> PromoCode:
    obj = PromoCode(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

async def update_promo(db: AsyncSession, promo_id: int, data: PromoCodeUpdate) -> PromoCode | None:
    obj = await get_promo_by_id(db, promo_id)
    if not obj: return None

    patch = data.model_dump(exclude_unset=True)
    for k, v in patch.items(): setattr(obj, k, v)

    await db.commit()
    await db.refresh(obj)
    return obj

async def delete_promo(db: AsyncSession, promo_id: int) -> bool:
    obj = await get_promo_by_id(db, promo_id)
    if not obj: return False
    await db.delete(obj)
    await db.commit()
    return True

                                                       
async def increment_times_used(db: AsyncSession, code: str, delta: int = 1) -> PromoCode | None:
    """
    Atomically increments times_used for promo by code.
    Returns updated row (or None if not found).
    """
    code = (code or "").strip()
    if not code: return None

    await db.execute(
        update(PromoCode)
        .where(PromoCode.code == code)
        .values(times_used=PromoCode.times_used + delta)
    )
    await db.commit()
    return await get_promo_by_code(db, code)

async def add_payout_amounts(db: AsyncSession, code: str, owner_add=0, lvl1_add=0, lvl2_add=0):
    """
    Atomically adds to *_amount_gained fields.
    Pass numbers/Decimals.
    """
    code = (code or "").strip()
    if not code: return None

    await db.execute(
        update(PromoCode)
        .where(PromoCode.code == code)
        .values(
            owner_amount_gained=PromoCode.owner_amount_gained + owner_add,
            lvl1_amount_gained=PromoCode.lvl1_amount_gained + lvl1_add,
            lvl2_amount_gained=PromoCode.lvl2_amount_gained + lvl2_add,
        )
    )
    await db.commit()
    return await get_promo_by_code(db, code)

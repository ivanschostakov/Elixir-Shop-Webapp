
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.favourite import Favourite
from src.database.models.product import Product
from src.database.schemas.favourite import (
    FavouriteBase,
    FavouriteCreate,
    FavouriteDelete,
)

async def get_user_favourites(db: AsyncSession, user_id: int) -> list[Favourite]:
    result = await db.execute(select(Favourite).where(Favourite.user_id == user_id))
    return list(result.scalars().all())

async def get_user_favourite_by_onec(db: AsyncSession, fav_in: FavouriteBase,) -> Favourite | None:
    result = await db.execute(select(Favourite).where(Favourite.user_id == fav_in.user_id, Favourite.onec_id == fav_in.onec_id))
    return result.scalars().first()

async def add_favourite(db: AsyncSession, fav_in: FavouriteCreate,) -> Favourite:
    existing = await get_user_favourite_by_onec(db, fav_in)
    if existing: return existing
    product_result = await db.execute(select(Product).where(Product.onec_id == fav_in.onec_id))
    product_exists = product_result.scalars().first()
    if not product_exists: raise ValueError(f"Product with onec_id={fav_in.onec_id} not found")

    fav = Favourite(user_id=fav_in.user_id, onec_id=fav_in.onec_id)
    db.add(fav)
    await db.commit()
    await db.refresh(fav)
    return fav

async def remove_favourite(db: AsyncSession, fav_in: FavouriteDelete,) -> bool:
    fav = await get_user_favourite_by_onec(db, fav_in)
    if not fav: return False
    await db.delete(fav)
    await db.commit()
    return True

async def is_favourite(db: AsyncSession, fav_in: FavouriteBase,) -> bool:
    result = await db.execute(select(Favourite).where(Favourite.user_id == fav_in.user_id, Favourite.onec_id == fav_in.onec_id))
    return result.scalars().first() is not None
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tg_category import TgCategory
from src.database.schemas.tg_category import TgCategoryCreate, TgCategoryUpdate

async def create_tg_category(db: AsyncSession, data: TgCategoryCreate) -> TgCategory:
    obj = TgCategory(name=data.name.strip(), description=data.description)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

async def list_tg_categories(db: AsyncSession) -> list[TgCategory]:
    res = await db.execute(select(TgCategory).order_by(TgCategory.name.asc()))
    return list(res.scalars().all())

async def get_tg_category_by_id(db: AsyncSession, category_id: int) -> TgCategory | None:
    res = await db.execute(select(TgCategory).where(TgCategory.id == category_id))
    return res.scalars().first()

async def get_tg_category_by_name(db: AsyncSession, name: str) -> TgCategory | None:
    name = name.strip()
    res = await db.execute(select(TgCategory).where(TgCategory.name == name))
    return res.scalars().first()

async def update_tg_category(db: AsyncSession, obj: TgCategory, data: TgCategoryUpdate) -> TgCategory:
    if data.name is not None: obj.name = data.name.strip()
    if data.description is not None: obj.description = data.description
    await db.commit()
    await db.refresh(obj)
    return obj

async def delete_tg_category(db: AsyncSession, obj: TgCategory) -> None:
    await db.delete(obj)
    await db.commit()
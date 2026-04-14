from typing import Any
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import Category
from ..schemas import CategoryCreate, CategoryUpdate

async def create_category(db: AsyncSession, category: CategoryCreate) -> Category:
    stmt = insert(Category).values(**category.dict())
    stmt = stmt.on_conflict_do_update(index_elements=["onec_id"], set_={"name": stmt.excluded.name, "code": stmt.excluded.code, "unit_onec_id": stmt.excluded.unit_onec_id})
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()

async def get_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(select(Category))
    return result.scalars().all()

async def get_category(db: AsyncSession, attr_name: str, value: Any) -> Category | None:
    if not hasattr(Category, attr_name): raise AttributeError(f"Category has no attribute '{attr_name}'")
    column = getattr(Category, attr_name)
    result = await db.execute(select(Category).where(column == value))
    return result.scalars().first()

async def update_category(db: AsyncSession, category_id: int, category_data: CategoryUpdate) -> Category | None:
    result = await db.execute(select(Category).where(Category.id == category_id))
    db_category = result.scalars().first()
    if db_category is None: return None
    for field, value in category_data.dict().items(): setattr(db_category, field, value)
    db.add(db_category)
    await db.commit()
    await db.refresh(db_category)
    return db_category

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from ..models.product import Product
from ..schemas import ProductUpdate
from ..schemas.product import ProductCreate

async def create_product(db: AsyncSession, product: ProductCreate) -> Product:
    stmt = insert(Product).values(**product.model_dump())
    stmt = stmt.on_conflict_do_update(index_elements=["onec_id"], set_={"name": stmt.excluded.name, "code": stmt.excluded.code, "description": stmt.excluded.description, "category_onec_id": stmt.excluded.category_onec_id})
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()

async def get_products(db: AsyncSession) -> list[Product]:
    result = await db.execute(select(Product))
    return result.scalars().all()

async def get_product_with_features(db: AsyncSession, onec_id: str) -> Product | None:
    result = await db.execute(select(Product).options(selectinload(Product.features)).where(Product.onec_id == onec_id))
    return result.scalars().first()

async def get_product(db: AsyncSession, attr_name: str, value: Any) -> Product | None:
    if not hasattr(Product, attr_name): raise AttributeError(f"Product has no attribute '{attr_name}'")
    column = getattr(Product, attr_name)
    result = await db.execute(select(Product).where(column == value))
    return result.scalars().first()

async def update_product(db: AsyncSession, product_id: int, product_data: ProductUpdate) -> Product | None:
    result = await db.execute(select(Product).where(Product.id == product_id))
    db_product = result.scalars().first()
    if db_product is None: return None

    for field, value in product_data.model_dump().items(): setattr(db_product, field, value)

    db.add(db_product)
    await db.commit()
    await db.refresh(db_product)
    return db_product

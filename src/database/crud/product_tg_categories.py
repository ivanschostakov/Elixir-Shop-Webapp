from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.product import Product
from src.database.models.tg_category import TgCategory

async def add_tg_category_to_product(db: AsyncSession, *, product_onec_id: str, tg_category_id: int,) -> Product:
    product = (await db.execute(select(Product).options(selectinload(Product.tg_categories)).where(Product.onec_id == product_onec_id))).scalars().first()
    if not product: raise ValueError("Product not found")

    category = (await db.execute(select(TgCategory).where(TgCategory.id == tg_category_id))).scalars().first()
    if not category: raise ValueError("Category not found")

    if category not in product.tg_categories: product.tg_categories.append(category)

    await db.commit()
    await db.refresh(product)
    return product

async def remove_tg_category_from_product(db: AsyncSession, *, product_onec_id: str, tg_category_id: int,) -> Product:
    product = (await db.execute(select(Product).options(selectinload(Product.tg_categories)).where(Product.onec_id == product_onec_id))).scalars().first()
    if not product: raise ValueError("Product not found")

    category = (await db.execute(select(TgCategory).where(TgCategory.id == tg_category_id))).scalars().first()
    if not category: raise ValueError("Category not found")
    elif category in product.tg_categories: product.tg_categories.remove(category)

    await db.commit()
    await db.refresh(product)
    return product
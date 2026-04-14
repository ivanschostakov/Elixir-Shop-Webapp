from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CartItem
from src.database.schemas import CartItemUpdate, CartItemCreate
from collections.abc import Sequence

async def get_cart_items(db: AsyncSession, cart_id: int) -> Sequence[CartItem]:
    result = await db.execute(select(CartItem).where(CartItem.cart_id == cart_id))
    return result.scalars().all()

async def get_cart_item_by_id(db: AsyncSession, item_id: int) -> CartItem | None:
    result = await db.execute(select(CartItem).where(CartItem.id == item_id))
    return result.scalar_one_or_none()

async def get_cart_item_by_product(db: AsyncSession, cart_id: int, product_onec_id: str, feature_onec_id: str) -> CartItem | None:
    result = await db.execute(select(CartItem).where(CartItem.cart_id == cart_id, CartItem.product_onec_id == product_onec_id, CartItem.feature_onec_id == feature_onec_id))
    return result.scalar_one_or_none()

async def add_or_increment_item(db: AsyncSession, cart_id: int, data: CartItemCreate) -> CartItem:
    item = await get_cart_item_by_product(db=db, cart_id=cart_id, product_onec_id=data.product_onec_id, feature_onec_id=data.feature_onec_id)
    if item: item.quantity += data.quantity
    else:
        item = CartItem(cart_id=cart_id, product_onec_id=data.product_onec_id, feature_onec_id=data.feature_onec_id, quantity=data.quantity)
        db.add(item)

    await db.commit()
    await db.refresh(item)
    return item

async def update_cart_item(db: AsyncSession, item: CartItem, data: CartItemUpdate) -> CartItem:
    if data.quantity is not None: item.quantity = data.quantity
    await db.commit()
    await db.refresh(item)
    return item

async def remove_cart_item(db: AsyncSession, item: CartItem) -> None:
    await db.delete(item)
    await db.commit()

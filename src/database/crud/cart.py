from sqlalchemy import select, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from datetime import datetime, timezone, timedelta

from config import UFA_TZ
from src.database.models import CartItem, Product
from src.database.models.cart import Cart
from src.database.schemas.cart import CartCreate, CartUpdate
from collections.abc import Sequence

async def get_cart_by_id(db: AsyncSession, cart_id: int) -> Cart | None:
    result = await db.execute(select(Cart).options(selectinload(Cart.items), selectinload(Cart.user)).where(Cart.id == cart_id))
    return result.scalar_one_or_none()

async def get_active_cart_by_order_fingerprint(db: AsyncSession, order_fingerprint: str) -> Cart | None:
    result = await db.execute(
        select(Cart).where(
            Cart.order_fingerprint == order_fingerprint,
            Cart.is_active.is_(True),
            Cart.is_canceled.is_(False),
        )
    )
    return result.scalar_one_or_none()

async def get_carts(db: AsyncSession, exclude_starting: bool = True) -> list[Cart] | None:
    result = await db.execute(select(Cart))
    carts: list[Cart] = result.scalars().all()
    return [cart for cart in carts if "ачальная" not in cart.name] if exclude_starting else carts

async def get_carts_by_date(db: AsyncSession, dt: datetime) -> list[Cart]:
    dt_msk = dt if dt.tzinfo else dt.replace(tzinfo=UFA_TZ)
    start_msk = dt_msk.astimezone(UFA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    end_msk = start_msk + timedelta(days=1)
    start_utc = start_msk.astimezone(timezone.utc)
    end_utc = end_msk.astimezone(timezone.utc)
    stmt = (select(Cart).where(Cart.created_at >= start_utc, Cart.created_at < end_utc).options(selectinload(Cart.user)).order_by(Cart.updated_at.desc()))
    carts = (await db.execute(stmt)).scalars().all()
    return [c for c in carts if "ачальная" not in (c.name or "")]

async def get_user_carts(db: AsyncSession, user_id: int, is_active: bool | None = None, exclude_starting: bool = True) -> Sequence[Cart]:
    query = select(Cart).where(Cart.user_id == user_id).options(selectinload(Cart.items).selectinload(CartItem.product).selectinload(Product.tg_categories), selectinload(Cart.items).selectinload(CartItem.feature), joinedload(Cart.promo), selectinload(Cart.user))
    if is_active is not None: query = query.where(Cart.is_active.is_(is_active))
    query = query.order_by(Cart.created_at.desc())
    result = await db.execute(query)
    carts: list[Cart] = result.scalars().all()
    return [cart for cart in carts if "ачальная" not in cart.name] if exclude_starting else carts

async def create_cart(db: AsyncSession, data: CartCreate) -> Cart:
    cart = Cart(**data.model_dump())
    db.add(cart)
    await db.commit()
    await db.refresh(cart)
    return cart

async def update_cart(db: AsyncSession, cart_id: int, payload: CartUpdate) -> Cart:
    res = await db.execute(select(Cart).where(Cart.id == cart_id))
    cart = res.scalar_one_or_none()
    if cart is None: raise ValueError(f"Cart {cart_id} not found")
    patch = payload.model_dump(exclude_unset=True, exclude_none=True)
    for k, v in patch.items(): setattr(cart, k, v)
    await db.commit()
    await db.refresh(cart)
    return cart

async def delete_cart(db: AsyncSession, cart: Cart) -> None:
    await db.delete(cart)
    await db.commit()

async def clear_cart(db: AsyncSession, cart_id: int) -> None:
    await db.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
    await db.commit()

async def get_user_carts_webapp(db: AsyncSession, user_id: int, is_active: bool | None = None, exclude_starting: bool = True,) -> Sequence[Cart]:
    stmt = (select(Cart).where(Cart.user_id == user_id).options(selectinload(Cart.items).selectinload(CartItem.product).selectinload(Product.tg_categories), selectinload(Cart.items).selectinload(CartItem.feature), joinedload(Cart.promo)).order_by(Cart.created_at.desc()))
    if is_active is not None: stmt = stmt.where(Cart.is_active.is_(is_active))
    if exclude_starting: stmt = stmt.where(or_(Cart.name.is_(None), ~Cart.name.ilike("%ачальная%")))
    res = await db.execute(stmt)
    return res.scalars().unique().all()

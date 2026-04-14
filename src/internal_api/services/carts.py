from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud import get_cart_by_id, get_carts, get_carts_by_date, get_user_carts, search_carts
from src.helpers import cart_analysis_text, user_carts_analytics_text
from src.internal_api.schemas import InternalCartRead, InternalSearchCartsOut, InternalTextOut
from src.internal_api.services.serializers import serialize_cart


async def get_carts_service(db: AsyncSession, *, exclude_starting: bool = True) -> list[InternalCartRead]:
    carts = await get_carts(db, exclude_starting=exclude_starting)
    return [serialize_cart(cart) for cart in (carts or []) if cart]


async def get_user_carts_service(
    db: AsyncSession,
    *,
    user_id: int,
    is_active: bool | None = None,
    exclude_starting: bool = True,
) -> list[InternalCartRead]:
    carts = await get_user_carts(db, user_id, is_active=is_active, exclude_starting=exclude_starting)
    return [serialize_cart(cart) for cart in carts if cart]


async def get_carts_by_date_service(db: AsyncSession, *, dt: datetime) -> list[InternalCartRead]:
    carts = await get_carts_by_date(db, dt)
    return [serialize_cart(cart) for cart in carts if cart]


async def get_cart_by_id_service(db: AsyncSession, *, cart_id: int) -> InternalCartRead | None:
    cart = await get_cart_by_id(db, cart_id)
    return serialize_cart(cart)


async def search_carts_service(
    db: AsyncSession,
    *,
    value: Any,
    page: int | None = None,
    limit: int | None = None,
) -> InternalSearchCartsOut:
    rows, total = await search_carts(db, value, page=page, limit=limit)
    return InternalSearchCartsOut(rows=[serialize_cart(row) for row in rows if row], total=total)


async def user_carts_analytics_text_service(
    db: AsyncSession,
    *,
    user_id: int,
    days: int = 30,
    top_n: int = 5,
    recent_n: int = 8,
) -> InternalTextOut:
    text = await user_carts_analytics_text(db, user_id, days=days, top_n=top_n, recent_n=recent_n)
    return InternalTextOut(text=text)


async def cart_analysis_text_service(db: AsyncSession, *, cart_id: int) -> InternalTextOut:
    text = await cart_analysis_text(db, cart_id)
    return InternalTextOut(text=text)

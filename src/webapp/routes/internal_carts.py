from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.internal_api.auth import get_internal_bot_auth_context
from src.internal_api.errors import InternalApiRoute
from src.internal_api.schemas import (
    InternalCartAnalysisIn,
    InternalCartRead,
    InternalGetCartsByDateIn,
    InternalGetCartsIn,
    InternalGetUserCartsIn,
    InternalSearchCartsIn,
    InternalSearchCartsOut,
    InternalTextOut,
    InternalUserCartsAnalyticsIn,
)
from src.internal_api.services.carts import (
    cart_analysis_text_service,
    get_cart_by_id_service,
    get_carts_by_date_service,
    get_carts_service,
    get_user_carts_service,
    search_carts_service,
    user_carts_analytics_text_service,
)

router = APIRouter(
    prefix="/internal/carts",
    tags=["internal-carts"],
    route_class=InternalApiRoute,
    dependencies=[Depends(get_internal_bot_auth_context)],
)


@router.post("/list", response_model=list[InternalCartRead])
async def get_carts(payload: InternalGetCartsIn, db: AsyncSession = Depends(get_db)) -> list[InternalCartRead]:
    return await get_carts_service(db, exclude_starting=payload.exclude_starting)


@router.post("/by-user", response_model=list[InternalCartRead])
async def get_user_carts(payload: InternalGetUserCartsIn, db: AsyncSession = Depends(get_db)) -> list[InternalCartRead]:
    return await get_user_carts_service(
        db,
        user_id=payload.user_id,
        is_active=payload.is_active,
        exclude_starting=payload.exclude_starting,
    )


@router.post("/by-date", response_model=list[InternalCartRead])
async def get_carts_by_date(
    payload: InternalGetCartsByDateIn,
    db: AsyncSession = Depends(get_db),
) -> list[InternalCartRead]:
    return await get_carts_by_date_service(db, dt=payload.dt)


@router.get("/{cart_id}", response_model=InternalCartRead | None)
async def get_cart_by_id(cart_id: int, db: AsyncSession = Depends(get_db)) -> InternalCartRead | None:
    return await get_cart_by_id_service(db, cart_id=cart_id)


@router.post("/search", response_model=InternalSearchCartsOut)
async def search_carts(payload: InternalSearchCartsIn, db: AsyncSession = Depends(get_db)) -> InternalSearchCartsOut:
    return await search_carts_service(db, value=payload.value, page=payload.page, limit=payload.limit)


@router.post("/analytics/user-carts", response_model=InternalTextOut)
async def user_carts_analytics_text(
    payload: InternalUserCartsAnalyticsIn,
    db: AsyncSession = Depends(get_db),
) -> InternalTextOut:
    return await user_carts_analytics_text_service(
        db,
        user_id=payload.user_id,
        days=payload.days,
        top_n=payload.top_n,
        recent_n=payload.recent_n,
    )


@router.post("/analysis", response_model=InternalTextOut)
async def cart_analysis_text(
    payload: InternalCartAnalysisIn,
    db: AsyncSession = Depends(get_db),
) -> InternalTextOut:
    return await cart_analysis_text_service(db, cart_id=payload.cart_id)

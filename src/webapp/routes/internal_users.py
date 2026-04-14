from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.database.schemas import UserCreate, UserUpdate
from src.internal_api.auth import get_internal_bot_auth_context
from src.internal_api.errors import InternalApiRoute
from src.internal_api.schemas import (
    InternalBooleanResult,
    InternalLookupUserIn,
    InternalSearchUsersIn,
    InternalSearchUsersOut,
    InternalUpdateUserNameIn,
    InternalUserRead,
)
from src.internal_api.services.users import (
    list_users_service,
    lookup_user_service,
    search_users_service,
    update_user_name_service,
    update_user_service,
    upsert_user_service,
)

router = APIRouter(
    prefix="/internal/users",
    tags=["internal-users"],
    route_class=InternalApiRoute,
    dependencies=[Depends(get_internal_bot_auth_context)],
)


@router.get("", response_model=list[InternalUserRead])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[InternalUserRead]:
    return await list_users_service(db)


@router.post("/lookup", response_model=InternalUserRead | None)
async def lookup_user(payload: InternalLookupUserIn, db: AsyncSession = Depends(get_db)) -> InternalUserRead | None:
    return await lookup_user_service(db, payload.column_name, payload.raw_value)


@router.post("", response_model=InternalUserRead)
async def upsert_user(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> InternalUserRead:
    return await upsert_user_service(db, payload)


@router.patch("/{tg_id}", response_model=InternalUserRead | None)
async def update_user(tg_id: int, payload: UserUpdate, db: AsyncSession = Depends(get_db)) -> InternalUserRead | None:
    return await update_user_service(db, tg_id, payload)


@router.patch("/{tg_id}/name", response_model=InternalBooleanResult)
async def update_user_name(
    tg_id: int,
    payload: InternalUpdateUserNameIn,
) -> InternalBooleanResult:
    ok = await update_user_name_service(tg_id, payload.first_name, payload.last_name)
    return InternalBooleanResult(ok=ok)


@router.post("/search", response_model=InternalSearchUsersOut)
async def search_users(payload: InternalSearchUsersIn, db: AsyncSession = Depends(get_db)) -> InternalSearchUsersOut:
    return await search_users_service(
        db,
        payload.by,
        payload.value,
        page=payload.page,
        limit=payload.limit,
    )

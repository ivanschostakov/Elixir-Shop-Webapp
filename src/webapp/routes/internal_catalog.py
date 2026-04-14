from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.database.schemas import UsedCodeCreate
from src.internal_api.auth import get_internal_bot_auth_context
from src.internal_api.errors import InternalApiRoute
from src.internal_api.schemas import InternalProductRead, InternalPromoRead, InternalUsedCodeRead
from src.internal_api.services.catalog import (
    create_used_code_service,
    get_product_with_features_service,
    get_used_code_by_code_service,
    list_promos_service,
)

router = APIRouter(
    prefix="/internal/catalog",
    tags=["internal-catalog"],
    route_class=InternalApiRoute,
    dependencies=[Depends(get_internal_bot_auth_context)],
)


@router.get("/products/{onec_id}", response_model=InternalProductRead | None)
async def get_product_with_features(onec_id: str, db: AsyncSession = Depends(get_db)) -> InternalProductRead | None:
    return await get_product_with_features_service(db, onec_id)


@router.get("/used-codes/{code}", response_model=InternalUsedCodeRead | None)
async def get_used_code_by_code(code: str, db: AsyncSession = Depends(get_db)) -> InternalUsedCodeRead | None:
    return await get_used_code_by_code_service(db, code)


@router.post("/used-codes", response_model=InternalUsedCodeRead)
async def create_used_code(payload: UsedCodeCreate, db: AsyncSession = Depends(get_db)) -> InternalUsedCodeRead:
    return await create_used_code_service(db, payload)


@router.get("/promos", response_model=list[InternalPromoRead])
async def list_promos(db: AsyncSession = Depends(get_db)) -> list[InternalPromoRead]:
    return await list_promos_service(db)

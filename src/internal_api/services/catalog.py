from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud import create_used_code, get_product_with_features, get_used_code_by_code, list_promos
from src.database.schemas import UsedCodeCreate
from src.internal_api.schemas import InternalProductRead, InternalPromoRead, InternalUsedCodeRead
from src.internal_api.services.serializers import serialize_product, serialize_promo, serialize_used_code


async def get_product_with_features_service(db: AsyncSession, onec_id: str) -> InternalProductRead | None:
    product = await get_product_with_features(db, onec_id)
    return serialize_product(product)


async def get_used_code_by_code_service(db: AsyncSession, code: str) -> InternalUsedCodeRead | None:
    used_code = await get_used_code_by_code(db, code)
    return serialize_used_code(used_code)


async def create_used_code_service(db: AsyncSession, data: UsedCodeCreate) -> InternalUsedCodeRead:
    used_code = await create_used_code(db, data)
    return serialize_used_code(used_code)


async def list_promos_service(db: AsyncSession) -> list[InternalPromoRead]:
    promos = await list_promos(db)
    return [serialize_promo(promo) for promo in promos if promo]

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud import create_used_code, get_product_with_features, get_used_code_by_code, list_promos
from src.database.schemas import UsedCodeCreate
from src.database.models import UsedCode, User
from src.internal_api.errors import InternalApiError
from src.internal_api.schemas import (
    InternalPremiumRedemptionCreate,
    InternalPremiumRedemptionRead,
    InternalProductRead,
    InternalPromoRead,
    InternalUsedCodeRead,
)
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


async def redeem_premium_order_service(
    db: AsyncSession,
    data: InternalPremiumRedemptionCreate,
) -> InternalPremiumRedemptionRead:
    code = data.code.strip().upper()
    user_result = await db.execute(select(User).where(User.tg_id == data.user_id).with_for_update())
    user = user_result.scalar_one_or_none()
    if user is None:
        raise InternalApiError(status_code=404, code="user_not_found", message="User was not found.")

    existing_result = await db.execute(select(UsedCode).where(UsedCode.code == code))
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.user_id != data.user_id:
            raise InternalApiError(status_code=409, code="order_already_redeemed", message="Order code is already redeemed.")
        return InternalPremiumRedemptionRead(
            user_id=user.tg_id,
            code=existing.code,
            price=existing.price,
            premium_until=user.premium_until or datetime.now(timezone.utc),
            already_redeemed=True,
        )

    now = datetime.now(timezone.utc)
    premium_base = user.premium_until if user.premium_until and user.premium_until > now else now
    user.premium_until = premium_base + timedelta(days=data.months * 30)
    used_code = UsedCode(user_id=data.user_id, code=code, price=data.price)
    db.add(used_code)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing_result = await db.execute(select(UsedCode).where(UsedCode.code == code))
        existing = existing_result.scalar_one_or_none()
        if existing is not None and existing.user_id == data.user_id:
            user = await db.get(User, data.user_id)
            if user is not None and user.premium_until is not None:
                return InternalPremiumRedemptionRead(
                    user_id=user.tg_id,
                    code=existing.code,
                    price=existing.price,
                    premium_until=user.premium_until,
                    already_redeemed=True,
                )
        raise InternalApiError(status_code=409, code="order_already_redeemed", message="Order code is already redeemed.") from exc

    return InternalPremiumRedemptionRead(
        user_id=user.tg_id,
        code=used_code.code,
        price=used_code.price,
        premium_until=user.premium_until,
    )


async def list_promos_service(db: AsyncSession) -> list[InternalPromoRead]:
    promos = await list_promos(db)
    return [serialize_promo(promo) for promo in promos if promo]

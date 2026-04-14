from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.internal_api.auth import get_internal_bot_auth_context
from src.internal_api.errors import InternalApiRoute
from src.internal_api.schemas import (
    InternalBooleanResult,
    InternalGetTotalRequestsIn,
    InternalGetUsagesIn,
    InternalGetUserUsageTotalsIn,
    InternalIdResult,
    InternalIncrementTokensIn,
    InternalTotalRequestsOut,
    InternalUsageReportOut,
    InternalUserUsageTotalsOut,
    InternalWriteUsageIn,
)
from src.internal_api.services.usage import (
    get_usages_service,
    get_user_total_requests_service,
    get_user_usage_totals_service,
    increment_tokens_service,
    write_usage_service,
)

router = APIRouter(
    prefix="/internal/usage",
    tags=["internal-usage"],
    route_class=InternalApiRoute,
    dependencies=[Depends(get_internal_bot_auth_context)],
)


@router.post("/tokens/increment", response_model=InternalBooleanResult)
async def increment_tokens(
    payload: InternalIncrementTokensIn,
    db: AsyncSession = Depends(get_db),
) -> InternalBooleanResult:
    await increment_tokens_service(db, payload.tg_id, input_inc=payload.input_inc, output_inc=payload.output_inc)
    return InternalBooleanResult(ok=True)


@router.post("/entries", response_model=InternalIdResult)
async def write_usage(payload: InternalWriteUsageIn, db: AsyncSession = Depends(get_db)) -> InternalIdResult:
    return await write_usage_service(
        db,
        user_id=payload.user_id,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        bot=payload.bot,
        usage_date=payload.usage_date,
        cached_input_tokens=payload.cached_input_tokens,
    )


@router.post("/total-requests", response_model=InternalTotalRequestsOut)
async def get_user_total_requests(
    payload: InternalGetTotalRequestsIn,
    db: AsyncSession = Depends(get_db),
) -> InternalTotalRequestsOut:
    total_requests = await get_user_total_requests_service(db, payload.user_id, payload.bots)
    return InternalTotalRequestsOut(total_requests=total_requests)


@router.post("/report", response_model=InternalUsageReportOut)
async def get_usages(payload: InternalGetUsagesIn, db: AsyncSession = Depends(get_db)) -> InternalUsageReportOut:
    return await get_usages_service(
        db,
        start_date=payload.start_date,
        end_date=payload.end_date,
        bot=payload.bot,
    )


@router.post("/user-totals", response_model=InternalUserUsageTotalsOut)
async def get_user_usage_totals(
    payload: InternalGetUserUsageTotalsIn,
    db: AsyncSession = Depends(get_db),
) -> InternalUserUsageTotalsOut:
    return await get_user_usage_totals_service(
        db,
        user_id=payload.user_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )

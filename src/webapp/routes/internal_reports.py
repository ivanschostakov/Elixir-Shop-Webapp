from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.internal_api.auth import get_internal_bot_auth_context
from src.internal_api.errors import InternalApiRoute
from src.internal_api.schemas import InternalUtmFunnelReportIn, InternalUtmFunnelReportOut
from src.internal_api.services.reports import get_utm_funnel_report_service

router = APIRouter(
    prefix="/internal/reports",
    tags=["internal-reports"],
    route_class=InternalApiRoute,
    dependencies=[Depends(get_internal_bot_auth_context)],
)


@router.post("/utm-funnel", response_model=InternalUtmFunnelReportOut)
async def get_utm_funnel_report(
    payload: InternalUtmFunnelReportIn,
    db: AsyncSession = Depends(get_db),
) -> InternalUtmFunnelReportOut:
    return await get_utm_funnel_report_service(
        db,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )

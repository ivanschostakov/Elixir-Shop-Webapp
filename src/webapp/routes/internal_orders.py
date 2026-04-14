from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.internal_api.auth import get_internal_bot_auth_context
from src.internal_api.errors import InternalApiRoute
from src.internal_api.schemas import InternalVerifyOrderIn, InternalVerifyOrderOut
from src.internal_api.services.orders import verify_order_code_service

router = APIRouter(
    prefix="/internal/orders",
    tags=["internal-orders"],
    route_class=InternalApiRoute,
    dependencies=[Depends(get_internal_bot_auth_context)],
)


@router.post("/verify", response_model=InternalVerifyOrderOut)
async def verify_order(payload: InternalVerifyOrderIn, db: AsyncSession = Depends(get_db)) -> InternalVerifyOrderOut:
    return await verify_order_code_service(db, payload.code)

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.database.schemas import UsedCodeCreate, UserCreate, UserUpdate
from src.internal_api.auth import InternalBotAuthContext, get_internal_bot_auth_context
from src.internal_api.schemas import (
    InternalCartAnalysisIn,
    InternalGetCartsByDateIn,
    InternalGetCartsIn,
    InternalGetTotalRequestsIn,
    InternalGetUsagesIn,
    InternalGetUserCartsIn,
    InternalGetUserUsageTotalsIn,
    InternalIncrementTokensIn,
    InternalLookupUserIn,
    InternalSearchCartsIn,
    InternalSearchUsersIn,
    InternalUpdateUserNameIn,
    InternalUserCartsAnalyticsIn,
    InternalWriteUsageIn,
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
from src.internal_api.services.catalog import (
    create_used_code_service,
    get_product_with_features_service,
    get_used_code_by_code_service,
    list_promos_service,
)
from src.internal_api.services.usage import (
    get_usages_service,
    get_user_total_requests_service,
    get_user_usage_totals_service,
    increment_tokens_service,
    write_usage_service,
)
from src.internal_api.services.users import (
    list_users_service,
    lookup_user_service,
    search_users_service,
    update_user_name_service,
    update_user_service,
    upsert_user_service,
)

router = APIRouter(prefix="/internal/bot", tags=["internal-bot"])
logger = logging.getLogger("webapp.internal_bot_rpc")
SLOW_RPC_THRESHOLD_MS = 3000


class BotRpcIn(BaseModel):
    action: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


def _validate_payload(model_cls, payload: dict[str, Any]) -> Any:
    try:
        return model_cls.model_validate(payload or {})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _require_int(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload[key])
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"{key} is required") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} must be an integer") from exc


async def _dispatch_legacy_rpc_action(action: str, payload: dict[str, Any], db: AsyncSession) -> Any:
    if action == "get_user":
        request = _validate_payload(InternalLookupUserIn, payload)
        return await lookup_user_service(db, request.column_name, request.raw_value)

    if action == "get_users":
        return await list_users_service(db)

    if action == "upsert_user":
        data = _validate_payload(UserCreate, (payload or {}).get("data") or {})
        return await upsert_user_service(db, data)

    if action == "update_user":
        data = _validate_payload(UserUpdate, (payload or {}).get("data") or {})
        tg_id = _require_int(payload, "tg_id")
        return await update_user_service(db, tg_id, data)

    if action == "update_user_name":
        request = _validate_payload(InternalUpdateUserNameIn, payload)
        tg_id = _require_int(payload, "tg_id")
        await update_user_name_service(tg_id, request.first_name, request.last_name)
        return True

    if action == "increment_tokens":
        request = _validate_payload(InternalIncrementTokensIn, payload)
        await increment_tokens_service(
            db,
            request.tg_id,
            input_inc=request.input_inc,
            output_inc=request.output_inc,
        )
        return True

    if action == "write_usage":
        request = _validate_payload(InternalWriteUsageIn, payload)
        return await write_usage_service(
            db,
            user_id=request.user_id,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            bot=request.bot,
            usage_date=request.usage_date,
            cached_input_tokens=request.cached_input_tokens,
        )

    if action == "get_user_total_requests":
        request = _validate_payload(InternalGetTotalRequestsIn, payload)
        return await get_user_total_requests_service(db, request.user_id, request.bots)

    if action == "get_usages":
        request = _validate_payload(InternalGetUsagesIn, payload)
        return await get_usages_service(
            db,
            start_date=request.start_date,
            end_date=request.end_date,
            bot=request.bot,
        )

    if action == "get_user_usage_totals":
        request = _validate_payload(InternalGetUserUsageTotalsIn, payload)
        return await get_user_usage_totals_service(
            db,
            user_id=request.user_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )

    if action == "get_product_with_features":
        return await get_product_with_features_service(db, str((payload or {}).get("onec_id") or ""))

    if action == "get_used_code_by_code":
        return await get_used_code_by_code_service(db, str((payload or {}).get("code") or ""))

    if action == "create_used_code":
        data = _validate_payload(UsedCodeCreate, (payload or {}).get("data") or {})
        return await create_used_code_service(db, data)

    if action == "list_promos":
        return await list_promos_service(db)

    if action == "get_carts":
        request = _validate_payload(InternalGetCartsIn, payload)
        return await get_carts_service(db, exclude_starting=request.exclude_starting)

    if action == "get_user_carts":
        request = _validate_payload(InternalGetUserCartsIn, payload)
        return await get_user_carts_service(
            db,
            user_id=request.user_id,
            is_active=request.is_active,
            exclude_starting=request.exclude_starting,
        )

    if action == "get_carts_by_date":
        request = _validate_payload(InternalGetCartsByDateIn, payload)
        return await get_carts_by_date_service(db, dt=request.dt)

    if action == "get_cart_by_id":
        return await get_cart_by_id_service(db, cart_id=_require_int(payload, "cart_id"))

    if action == "search_users":
        request = _validate_payload(InternalSearchUsersIn, payload)
        return await search_users_service(
            db,
            request.by,
            request.value,
            page=request.page,
            limit=request.limit,
        )

    if action == "search_carts":
        request = _validate_payload(InternalSearchCartsIn, payload)
        return await search_carts_service(db, value=request.value, page=request.page, limit=request.limit)

    if action == "user_carts_analytics_text":
        request = _validate_payload(InternalUserCartsAnalyticsIn, payload)
        result = await user_carts_analytics_text_service(
            db,
            user_id=request.user_id,
            days=request.days,
            top_n=request.top_n,
            recent_n=request.recent_n,
        )
        return result.text

    if action == "cart_analysis_text":
        request = _validate_payload(InternalCartAnalysisIn, payload)
        result = await cart_analysis_text_service(db, cart_id=request.cart_id)
        return result.text

    raise HTTPException(status_code=400, detail=f"Unknown bot action: {action}")


@router.post("/rpc")
async def bot_rpc(
    body: BotRpcIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: InternalBotAuthContext = Depends(get_internal_bot_auth_context),
):
    action = body.action
    payload = body.payload
    request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex[:12]
    payload_keys = ",".join(sorted(payload.keys())) if isinstance(payload, dict) else "non-dict"
    started = time.monotonic()

    logger.warning(
        "RPC deprecated | id=%s | bot=%s | action=%s | payload_keys=[%s]",
        request_id,
        auth.label,
        action,
        payload_keys,
    )

    try:
        result = await _dispatch_legacy_rpc_action(action, payload, db)
    except HTTPException as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
        logger.log(
            level,
            "RPC handled error | id=%s | bot=%s | action=%s | status=%d | elapsed_ms=%d | detail=%r",
            request_id,
            auth.label,
            action,
            exc.status_code,
            elapsed_ms,
            exc.detail,
        )
        raise
    except Exception:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.exception(
            "RPC unhandled error | id=%s | bot=%s | action=%s | elapsed_ms=%d",
            request_id,
            auth.label,
            action,
            elapsed_ms,
        )
        raise

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if elapsed_ms >= SLOW_RPC_THRESHOLD_MS:
        logger.warning(
            "RPC slow | id=%s | bot=%s | action=%s | elapsed_ms=%d",
            request_id,
            auth.label,
            action,
            elapsed_ms,
        )
    else:
        logger.info(
            "RPC ok | id=%s | bot=%s | action=%s | elapsed_ms=%d",
            request_id,
            auth.label,
            action,
            elapsed_ms,
        )

    return {"ok": True, "result": jsonable_encoder(result)}

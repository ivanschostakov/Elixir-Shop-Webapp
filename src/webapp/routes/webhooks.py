import re

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from src.database.crud import delete_used_code, get_cart_by_id, get_promo_by_code, get_used_code_by_code, get_user, update_cart, update_promo, update_user
from src.database import get_db
from src.database.models import Cart
from src.webapp.routes.promocodes import Q2, D100
from src.database.schemas import CartUpdate, PromoCodeUpdate, UserUpdate
from src.services.intellectmoney import intellectmoney
from src.services.order_fulfillment import create_delivery_from_snapshot
from src.internal_api.services.orders import verify_order_code_service
from src.moysklad.order_sync import (
    MOY_SKLAD_INVOICEOUT_STATE_PAID,
    MOY_SKLAD_STATE_INVOICE_PAID,
    sync_moysklad_customerorder_state,
    sync_moysklad_invoiceout_state,
)
from src.webapp.schemas import VerifyOrderIn, VerifyOrderOut
from src.webapp.routes.payments import reconcile_sbp_payment

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
PREMIUM_PRICE_PER_MONTH = Decimal("5000")
TRANSIENT_AMOCRM_STATUSES = {401, 403, 429, 500, 502, 503, 504}


async def _get_cart_by_lead_id(db: AsyncSession, lead_id: int) -> Cart | None:
    result = await db.execute(select(Cart).where(Cart.amocrm_lead_id == lead_id))
    return result.scalar_one_or_none()


async def _create_delivery_if_needed(db: AsyncSession, cart: Cart) -> Cart:
    if not cart or cart.delivery_created_at:
        return cart
    snapshot = cart.checkout_snapshot
    if not isinstance(snapshot, dict) or not snapshot:
        raise RuntimeError(f"Cart {cart.id} has no checkout snapshot for delivery creation")

    delivery_sum, provider_ref = await create_delivery_from_snapshot(snapshot, str(cart.id))
    patch: dict[str, object] = {
        "delivery_created_at": datetime.now(timezone.utc),
        "delivery_provider_ref": provider_ref,
    }
    if delivery_sum not in (None, ""):
        patch["delivery_sum"] = delivery_sum
    if (cart.selected_delivery_service or "").strip().lower() == "yandex" and provider_ref:
        patch["yandex_request_id"] = provider_ref
    return await update_cart(db, cart.id, CartUpdate(**patch))


def _subtract_premium_duration(premium_until: datetime, price: Decimal) -> datetime:
    if price <= 0:
        return premium_until

    whole_months = int(price // PREMIUM_PRICE_PER_MONTH) if PREMIUM_PRICE_PER_MONTH else 0
    if whole_months <= 0:
        return premium_until
    return premium_until - relativedelta(months=whole_months)


async def _reverse_used_code_premium_if_needed(db: AsyncSession, cart: Cart, order_code: str) -> None:
    if not order_code:
        return

    used_code = await get_used_code_by_code(db, order_code)
    if not used_code:
        return

    user = await get_user(db, "tg_id", cart.user_id)
    if not user:
        return

    if user.premium_until:
        new_premium_until = _subtract_premium_duration(user.premium_until, Decimal(str(used_code.price or 0)))
        await update_user(db, user.tg_id, UserUpdate(premium_until=new_premium_until))

    await delete_used_code(db, used_code.id)

@router.get("/amocrm")
async def get_webhook(request: Request):
    try: print(await request.json())
    except: print(await request.body())

@router.post("/amocrm")
async def get_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    q = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)

    lead_id = int((q.get("leads[status][0][id]") or ["0"])[0] or "0")
    status_id = int((q.get("leads[status][0][status_id]") or ["0"])[0] or "0")
    pipeline_id = int((q.get("leads[status][0][pipeline_id]") or ["0"])[0] or "0")
    if not lead_id: return JSONResponse({"ok": True, "ignored": "no lead_id"})
    from src.amocrm.client import amocrm, AmoCRMRecoverableError
    if pipeline_id and pipeline_id != amocrm.PIPELINE_ID: return JSONResponse({"ok": True, "ignored": "wrong pipeline"})

    try:
        try:
            lead = await amocrm._get(f"/api/v4/leads/{lead_id}")
        except AmoCRMRecoverableError as exc:
            amocrm.logger.warning(
                "Temporary AmoCRM issue during webhook lead fetch lead_id=%s: %s. Returning 200 to avoid retry storm.",
                lead_id,
                exc,
            )
            return JSONResponse({"ok": True, "ignored": "amocrm_temporal_failure"})
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in TRANSIENT_AMOCRM_STATUSES:
                amocrm.logger.warning(
                    "Transient AmoCRM HTTP %s during webhook lead fetch lead_id=%s. Returning 200 to avoid retry storm.",
                    status_code,
                    lead_id,
                )
                return JSONResponse({"ok": True, "ignored": f"amocrm_http_{status_code}"})
            raise

        name = lead.get("name") or ""
        status_id = int(lead.get("status_id") or status_id or 0)
        pipeline_id = int(lead.get("pipeline_id") or pipeline_id or 0)
        if pipeline_id and pipeline_id != amocrm.PIPELINE_ID: return JSONResponse({"ok": True, "ignored": "pipeline mismatch"})
        m = re.search(r"№\s*(\d+)", name)
        if not m:
            amocrm.logger.warning("Lead %s name has no cart id: %r", lead_id, name)
            cart = await _get_cart_by_lead_id(db, lead_id)
            if not cart:
                return JSONResponse({"ok": True, "ignored": "no cart id in lead name"})
            cart_id = cart.id
        else:
            cart_id = int(m.group(1))
            cart = await get_cart_by_id(db, cart_id)
            if not cart:
                cart = await _get_cart_by_lead_id(db, lead_id)
                if not cart:
                    amocrm.logger.warning("Lead %s resolved cart id %s, but local cart not found", lead_id, cart_id)
                    return JSONResponse({"ok": True, "ignored": "cart not found"})
                cart_id = cart.id

        order_code = str(cart.id)
        status_text = amocrm.STATUS_WORDS.get(status_id, f"Статус {status_id}")
        print(cart_id, '->', status_text)
        is_active = True if status_id not in [143, 142, 82657618] else False
        is_paid = True if status_id in amocrm.PAID_STATUS_IDS else None
        is_canceled = True if status_id in [82657618, 143] else None
        is_shipped = True if status_id in [76566302, 76566306] else None
        cart = await update_cart(db, cart_id, CartUpdate(status=status_text, is_active=is_active, is_paid=is_paid, is_canceled=is_canceled, is_shipped=is_shipped))
        if status_id == 143:
            await _reverse_used_code_premium_if_needed(db, cart, order_code)
        if status_id in amocrm.PAID_STATUS_IDS:
            cart = await _create_delivery_if_needed(db, cart)
            await sync_moysklad_customerorder_state(cart, state_name=MOY_SKLAD_STATE_INVOICE_PAID)
            await sync_moysklad_invoiceout_state(cart, state_name=MOY_SKLAD_INVOICEOUT_STATE_PAID)
        if not cart.is_active and not cart.promo_gains_given:
            print(cart.to_dict())
            code = cart.promo_code
            promo_code = await get_promo_by_code(db, code)
            if promo_code:
                print(promo_code.code)
                owner_pct = Decimal(promo_code.owner_pct or 0)
                lvl1_pct = Decimal(promo_code.lvl1_pct or 0)
                lvl2_pct = Decimal(promo_code.lvl2_pct or 0)

                new_owner_gained = (Decimal(promo_code.owner_amount_gained or 0) + (cart.sum * owner_pct / D100)).quantize(Q2, rounding=ROUND_HALF_UP)
                new_lvl1_gained  = (Decimal(promo_code.lvl1_amount_gained  or 0) + (cart.sum * lvl1_pct  / D100)).quantize(Q2, rounding=ROUND_HALF_UP)
                new_lvl2_gained  = (Decimal(promo_code.lvl2_amount_gained  or 0) + (cart.sum * lvl2_pct  / D100)).quantize(Q2, rounding=ROUND_HALF_UP)
                promo_code = await update_promo(db, promo_code.id, PromoCodeUpdate(owner_amount_gained=new_owner_gained, lvl1_amount_gained=new_lvl1_gained, lvl2_amount_gained=new_lvl2_gained))
                amocrm.logger.info(f"Promo code {promo_code.code} gains updated:\n"
                                   f"{promo_code.owner_name} — {promo_code.owner_amount_gained}\n"
                                   f"{promo_code.lvl1_name} — {promo_code.lvl1_amount_gained}\n"
                                   f"{promo_code.lvl2_name} — {promo_code.lvl2_amount_gained}\n")
            cart = await update_cart(db, cart.id, CartUpdate(promo_gains_given=True))

        amocrm.logger.info("Lead %s cart updated successfully", lead_id)
        return JSONResponse({"ok": True, "cart_id": cart_id, "lead_id": lead_id, "status_id": status_id})

    except Exception:
        amocrm.logger.exception("Webhook failed lead_id=%s", lead_id)
        return JSONResponse({"ok": False, "ignored": "exception"}, status_code=500)

@router.put("/amocrm")
async def get_webhook(request: Request):
    try: print(await request.json())
    except: print(await request.body())


@router.post("/intellectmoney")
async def intellectmoney_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    payload = {key: str(value) for key, value in form.items()}
    if not intellectmoney.verify_webhook_hash(payload):
        return PlainTextResponse("ERROR", status_code=400)

    order_id_raw = payload.get("OrderId") or ""
    if not order_id_raw.isdigit():
        return PlainTextResponse("ERROR", status_code=400)

    cart = await get_cart_by_id(db, int(order_id_raw))
    if not cart:
        return PlainTextResponse("ERROR", status_code=404)

    cart = await update_cart(
        db,
        cart.id,
        CartUpdate(payment_provider="intellectmoney", payment_invoice_id=payload.get("PaymentId") or None),
    )
    payment_status_raw = payload.get("PaymentStatus")
    payment_status_code = int(payment_status_raw) if payment_status_raw and payment_status_raw.isdigit() else None
    await reconcile_sbp_payment(
        db,
        cart,
        payment_status_code=payment_status_code,
        payment_data=payload.get("PaymentData"),
        invoice_id=payload.get("PaymentId"),
    )
    return PlainTextResponse("OK")

@router.delete("/amocrm")
async def get_webhook(request: Request):
    try: print(await request.json())
    except: print(await request.body())

@router.post("/verify-order", response_model=VerifyOrderOut)
async def verify_order(payload: VerifyOrderIn, db: AsyncSession = Depends(get_db)) -> VerifyOrderOut:
    return await verify_order_code_service(db, payload.code)

import logging
import socket
import hashlib
import json

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import WEBAPP_BASE_DOMAIN
from src.amocrm.client import AmoCRMRecoverableError, amocrm
from src.database import get_db
from src.database.crud import (
    add_or_increment_item,
    clear_cart,
    create_cart,
    get_active_cart_by_order_fingerprint,
    get_cart_by_id,
    get_promo_by_code,
    update_cart,
    update_promo,
    update_user,
    upsert_user,
)
from src.database.schemas import CartCreate, CartItemCreate, CartUpdate, PromoCodeUpdate, UserCreate, UserUpdate
from src.helpers import format_order_for_amocrm, normalize_address_for_cf
from src.services.intellectmoney import IntellectMoneyError, intellectmoney
from src.services.geo import enrich_delivery_address_payload
from src.services.order_fulfillment import resolve_delivery_sum
from src.moysklad.order_sync import (
    MOY_SKLAD_INVOICEOUT_STATE_PAID,
    MOY_SKLAD_STATE_INVOICE_PAID,
    MOY_SKLAD_STATE_INVOICE_SENT,
    sync_cart_to_moysklad_safe,
    sync_moysklad_customerorder_state,
    sync_moysklad_invoiceout_state,
)
from src.tg_methods import normalize_phone
from src.webapp.routes.cart import cart_json
from src.webapp.schemas import CheckoutData

Q2 = Decimal("0.01")
PAYMENT_STATUS_BY_CODE = {
    3: "created",
    4: "canceled",
    5: "paid",
    6: "hold",
    7: "partial",
    8: "refunded",
}
PENDING_PAYMENT_STEPS = {"", "Created", "InProcess", "SendTo3DS"}
FINAL_PAYMENT_STATUSES = {"paid", "canceled", "error", "refunded"}


def _format_validation_reasons(errors):
    reasons = []
    for error in errors:
        location = ".".join(str(part) for part in error.get("loc", []))
        message = error.get("msg", "Validation error")
        reasons.append(f"{location}: {message}" if location else message)
    return reasons


def _extract_422_reason(detail):
    if isinstance(detail, list):
        if all(isinstance(item, dict) for item in detail):
            return _format_validation_reasons(detail)
        return [str(item) for item in detail]

    if isinstance(detail, dict):
        nested_detail = detail.get("detail")
        if isinstance(nested_detail, list) and all(isinstance(item, dict) for item in nested_detail):
            return _format_validation_reasons(nested_detail)
        if "reason" in detail:
            return detail["reason"]
        return str(detail)

    return str(detail)


class PaymentLoggingRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                reasons = _format_validation_reasons(exc.errors())
                log.exception("Validation error on %s: %s", request.url.path, reasons)
                return JSONResponse(status_code=422, content={"detail": exc.errors(), "reason": reasons})
            except HTTPException as exc:
                log.exception("HTTPException on %s: status=%s detail=%s", request.url.path, exc.status_code, exc.detail)
                if exc.status_code == 422:
                    return JSONResponse(
                        status_code=422,
                        content={"detail": exc.detail, "reason": _extract_422_reason(exc.detail)},
                        headers=exc.headers,
                    )
                raise
            except Exception:
                log.exception("Unhandled exception on %s", request.url.path)
                raise

        return custom_route_handler


router = APIRouter(prefix="/payments", tags=["payments"], route_class=PaymentLoggingRoute)
log = logging.getLogger(__name__)


def _to_decimal(value: Decimal | float | int | str | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Q2, rounding=ROUND_HALF_UP)


def _full_name(contact_info: dict[str, str]) -> str:
    return " ".join(part for part in [(contact_info.get("name") or "").strip(), (contact_info.get("surname") or "").strip()] if part).strip()


def _payment_status_from_step(payment_step: str | None) -> str:
    step = (payment_step or "").strip()
    if step == "OK":
        return "paid"
    if step == "Error":
        return "error"
    if step in PENDING_PAYMENT_STEPS:
        return "pending"
    return step.lower() if step else "pending"


def _payment_status_from_code(payment_status_code: int | None) -> str | None:
    if payment_status_code is None:
        return None
    return PAYMENT_STATUS_BY_CODE.get(int(payment_status_code))


def _parse_payment_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _base_domain(request: Request) -> str:
    configured = (WEBAPP_BASE_DOMAIN or "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _intellectmoney_urls(request: Request, order_number: int) -> dict[str, str]:
    base = _base_domain(request)
    process_url = f"{base}/#/payment-process?order_id={order_number}"
    success_url = f"{process_url}&result=success"
    fail_url = f"{process_url}&result=failed"
    return {
        "success_url": success_url,
        "fail_url": fail_url,
        # IntellectMoney uses BackUrl for the "Back to store" action after a successful payment.
        "back_url": success_url,
        "result_url": f"{base}/webhooks/intellectmoney",
    }


def _detect_site_ip(request: Request) -> str:
    host = urlsplit(_base_domain(request)).hostname
    if host:
        try:
            return socket.gethostbyname(host)
        except OSError:
            log.warning("Unable to resolve base domain host %s for IntellectMoney; falling back", host)

    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate

    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _delivery_string(selected_delivery_service: str, address_str: str | None) -> str:
    service = (selected_delivery_service or "").strip().upper()
    if not service:
        return "Не указан"
    if address_str:
        return f"{service}: {address_str}"
    return service


def _normalize_fingerprint_text(value: object) -> str:
    raw = str(value or "").strip()
    return " ".join(raw.split()).casefold()


def _aggregate_checkout_items(items: list[dict]) -> dict[tuple[str, str], int]:
    item_quantities: dict[tuple[str, str], int] = {}
    for item in items or []:
        product_id = str(item.get("id") or "").strip()
        feature_id = str(item.get("featureId") or "").strip()
        quantity = int(item.get("qty") or 0)
        if not product_id or not feature_id or quantity <= 0:
            continue
        key = (product_id, feature_id)
        item_quantities[key] = item_quantities.get(key, 0) + quantity
    return item_quantities


def _build_order_fingerprint(*, user_id: int | str, address_str: str, items: list[dict]) -> str:
    normalized_items = [
        {"product_id": product_id, "feature_id": feature_id, "qty": quantity}
        for (product_id, feature_id), quantity in sorted(_aggregate_checkout_items(items).items())
    ]
    fingerprint_payload = {
        "user_id": int(user_id),
        "delivery_address": _normalize_fingerprint_text(address_str),
        "items": normalized_items,
    }
    payload_json = json.dumps(fingerprint_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _raise_duplicate_order(existing_cart_id: int) -> None:
    raise HTTPException(
        status_code=409,
        detail=f"У вас уже есть активный заказ #{existing_cart_id} с таким же адресом и составом.",
    )


def _can_resume_incomplete_order(cart) -> bool:
    status = (cart.payment_status or "").strip().lower()
    return (
        bool(cart.is_active)
        and not bool(cart.is_canceled)
        and not bool(cart.is_paid)
        and cart.amocrm_lead_id is None
        and not cart.payment_invoice_id
        and status == "draft"
    )


def _payment_error_text(payment_status: str | None, payment_step: str | None = None) -> str | None:
    if payment_status == "canceled":
        return "Платеж был отменен"
    if payment_status == "error":
        return "Ошибка оплаты"
    if payment_status == "refunded":
        return "Платеж возвращен"
    if payment_status == "hold":
        return "Платеж захолдирован"
    if payment_status == "partial":
        return "Платеж оплачен частично"
    if payment_step and payment_step not in PENDING_PAYMENT_STEPS:
        return payment_step
    return None


def _amocrm_payment_label(payment_method: str | None) -> str:
    method = (payment_method or "").strip().lower()
    if method == "sbp":
        return "IntellectMoney"
    if method == "later":
        return "Оплата позже"
    return payment_method or "Не указан"


async def _apply_promocode(
    db: AsyncSession,
    total: Decimal,
    discountable_total: Decimal,
    promocode_raw: str | None,
) -> tuple[Decimal, str | None]:
    promocode = (promocode_raw or "").strip()
    if not promocode:
        return total, None

    promo_code = await get_promo_by_code(db, promocode)
    if not promo_code:
        return total, None

    if total <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than 0")

    discount_pct = Decimal(str(promo_code.discount_pct or 0))
    if discount_pct <= 0 or discountable_total <= 0:
        return total, promo_code.code

    discounted_discountable_total = (discountable_total * (Decimal("1") - (discount_pct / Decimal("100")))).quantize(Q2, rounding=ROUND_HALF_UP)
    discounted_total = (total - discountable_total + discounted_discountable_total).quantize(Q2, rounding=ROUND_HALF_UP)
    promo_code_update = PromoCodeUpdate(times_used=(promo_code.times_used or 0) + 1)
    await update_promo(db, promo_code.id, promo_code_update)
    return discounted_total, promo_code.code


def _build_checkout_snapshot(
    payload: CheckoutData,
    *,
    checkout_items: list[dict],
    total: Decimal,
    delivery_sum: Decimal,
    normalized_phone: str,
    selected_delivery: dict,
    promocode: str | None,
    commentary_text: str,
) -> dict:
    snapshot = {
        "user_id": payload.user_id,
        "tg_nick": payload.tg_nick,
        "source": payload.source or "telegram",
        "payment_method": payload.payment_method,
        "contact_info": {
            **payload.contact_info.model_dump(),
            "phone": normalized_phone,
        },
        "checkout_data": {
            **deepcopy(payload.checkout_data),
            "items": checkout_items,
            "total": float(total),
        },
        "selected_delivery": deepcopy(selected_delivery),
        "selected_delivery_service": payload.selected_delivery_service,
        "commentary": commentary_text,
        "promocode": promocode or "Не указан",
    }
    if snapshot["selected_delivery"] is not None:
        snapshot["selected_delivery"]["delivery_sum"] = float(delivery_sum)
    return snapshot


def _normalize_commentary_text(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.lower() == "не указан":
        return ""
    return normalized


def _cart_item_quantities(cart) -> dict[tuple[str, str], int]:
    quantities: dict[tuple[str, str], int] = {}
    for item in getattr(cart, "items", []) or []:
        product_id = str(item.product_onec_id or "").strip()
        feature_id = str(item.feature_onec_id or "").strip()
        quantity = int(item.quantity or 0)
        if not product_id or not feature_id or quantity <= 0:
            continue
        quantities[(product_id, feature_id)] = quantity
    return quantities


async def _sync_cart_items(db: AsyncSession, cart, items: list[dict]):
    desired_quantities = _aggregate_checkout_items(items)
    cart_with_items = await get_cart_by_id(db, cart.id) or cart
    if _cart_item_quantities(cart_with_items) == desired_quantities:
        return cart_with_items

    await clear_cart(db, cart.id)
    for (product_id, feature_id), quantity in desired_quantities.items():
        await add_or_increment_item(
            db,
            cart.id,
            CartItemCreate(
                product_onec_id=product_id,
                feature_onec_id=feature_id,
                quantity=quantity,
            ),
        )
    return await get_cart_by_id(db, cart.id) or cart_with_items


async def _finalize_prepared_order(
    db: AsyncSession,
    *,
    cart,
    user,
    payload: CheckoutData,
    contact_info: dict[str, str],
    normalized_phone: str,
    selected_delivery_service: str,
    selected_delivery: dict,
    delivery_sum: Decimal,
    total: Decimal,
    total_with_delivery: Decimal,
    address_str: str,
    promo_code: str | None,
    commentary_text: str,
    snapshot: dict,
) -> dict[str, object]:
    lead_name = _full_name(contact_info) or f"Заказ #{cart.id}"
    contact: dict[str, object] = {}
    contact_id = user.contact_id
    try:
        contact = await amocrm.find_or_create_contact(
            lead_name=lead_name,
            phone=normalized_phone,
            email=contact_info["email"],
            contact_id=user.contact_id,
        )
        resolved_contact_id = contact.get("id") if isinstance(contact, dict) else None
        if resolved_contact_id:
            contact_id = int(resolved_contact_id)
            if contact_id != user.contact_id:
                user = await update_user(db, user.tg_id, UserUpdate(contact_id=contact_id))
    except AmoCRMRecoverableError:
        log.warning(
            "AmoCRM contact sync temporarily unavailable for cart=%s, proceeding without CRM contact update",
            cart.id,
            exc_info=True,
        )

    if not cart.amocrm_lead_id:
        try:
            existing_lead = await amocrm.find_lead_by_order_number(cart.id)
            if existing_lead:
                lead_id = int(existing_lead["id"])
                log.warning("Reattached existing amoCRM lead %s to cart %s during retry", lead_id, cart.id)
            else:
                tariff = (
                    selected_delivery.get("deliveryMode")
                    or (selected_delivery.get("tariff") or {}).get("tariff_name")
                    or (selected_delivery.get("tariff") or {}).get("tariff_code")
                )
                note_text = format_order_for_amocrm(
                    cart.id,
                    snapshot,
                    selected_delivery_service,
                    tariff,
                    commentary_text,
                    promo_code or "Не указан",
                    delivery_sum,
                )
                lead = await amocrm.create_lead_with_contact_and_note(
                    lead_name=lead_name,
                    price=int(total_with_delivery.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                    address_str=address_str,
                    phone=normalized_phone,
                    email=contact_info["email"],
                    order_number=str(cart.id),
                    delivery_service=selected_delivery_service,
                    note_text=note_text,
                    payment_method=_amocrm_payment_label(payload.payment_method),
                    tg_nick=payload.tg_nick,
                    status_id=amocrm.STATUS_IDS["main"],
                    delivery_sum=delivery_sum,
                    promo_code=promo_code,
                    contact_id=contact_id,
                )
                lead_id = int(lead["id"])
                log.info("Created amoCRM lead %s for cart %s", lead_id, cart.id)
            cart = await update_cart(db, cart.id, CartUpdate(amocrm_lead_id=lead_id))
        except AmoCRMRecoverableError:
            log.warning(
                "AmoCRM lead sync temporarily unavailable for cart=%s, proceeding without CRM lead binding",
                cart.id,
                exc_info=True,
            )

    return {
        "cart": cart,
        "user": user,
        "contact": contact,
        "contact_info": contact_info,
        "selected_delivery": selected_delivery,
        "delivery_sum": delivery_sum,
        "total": total,
        "total_with_delivery": total_with_delivery,
        "address_str": address_str,
        "promo_code": promo_code,
        "commentary_text": commentary_text,
    }


async def _resume_incomplete_order(
    db: AsyncSession,
    *,
    cart,
    user,
    payload: CheckoutData,
    items: list[dict],
    contact_info: dict[str, str],
    normalized_phone: str,
    selected_delivery: dict,
    commentary_text: str,
    address_str: str,
) -> dict[str, object]:
    selected_delivery_service = cart.selected_delivery_service or payload.selected_delivery_service
    resumed_selected_delivery = deepcopy(cart.selected_delivery_payload or selected_delivery or {})
    resumed_address_payload = resumed_selected_delivery.get("address")
    if isinstance(resumed_address_payload, dict):
        await enrich_delivery_address_payload(resumed_address_payload)
    resumed_delivery_sum = _to_decimal(cart.delivery_sum)
    resumed_selected_delivery["delivery_sum"] = float(resumed_delivery_sum)
    resumed_total = _to_decimal(cart.sum)
    resumed_promo_code = cart.promo_code
    resumed_commentary_text = _normalize_commentary_text(commentary_text) or _normalize_commentary_text(cart.commentary)
    resumed_address_str = normalize_address_for_cf(resumed_selected_delivery.get("address")) or address_str
    resumed_snapshot = deepcopy(
        cart.checkout_snapshot
        or _build_checkout_snapshot(
            payload,
            checkout_items=items,
            total=resumed_total,
            delivery_sum=resumed_delivery_sum,
            normalized_phone=normalized_phone,
            selected_delivery=resumed_selected_delivery,
            promocode=resumed_promo_code,
            commentary_text=resumed_commentary_text,
        )
    )
    resumed_snapshot["user_id"] = payload.user_id
    resumed_snapshot["tg_nick"] = payload.tg_nick
    resumed_snapshot["source"] = payload.source or resumed_snapshot.get("source") or "telegram"
    resumed_snapshot["payment_method"] = payload.payment_method
    resumed_snapshot["contact_info"] = {
        **contact_info,
        "phone": normalized_phone,
    }
    resumed_snapshot["checkout_data"] = {
        **deepcopy(resumed_snapshot.get("checkout_data") or payload.checkout_data),
        "items": items,
        "total": float(resumed_total),
    }
    resumed_snapshot["selected_delivery"] = deepcopy(resumed_selected_delivery)
    resumed_snapshot["selected_delivery_service"] = selected_delivery_service
    resumed_snapshot["commentary"] = resumed_commentary_text
    resumed_snapshot["promocode"] = resumed_promo_code or "Не указан"
    resumed_total_with_delivery = (resumed_total + resumed_delivery_sum).quantize(Q2, rounding=ROUND_HALF_UP)

    log.warning("Resuming incomplete order %s after previous setup failure", cart.id)
    cart = await update_cart(
        db,
        cart.id,
        CartUpdate(
            phone=normalized_phone,
            email=contact_info["email"],
            commentary=resumed_commentary_text,
            payment_method=payload.payment_method,
            payment_status="draft",
            payment_error="",
            delivery_string=_delivery_string(selected_delivery_service, resumed_address_str),
            selected_delivery_service=selected_delivery_service,
            selected_delivery_payload=resumed_selected_delivery,
            checkout_snapshot=resumed_snapshot,
            status=cart.status or amocrm.STATUS_WORDS.get(amocrm.STATUS_IDS["main"], "Создан"),
            is_active=True,
            is_paid=False,
            is_canceled=False,
            is_shipped=False,
        ),
    )
    cart = await _sync_cart_items(db, cart, items)
    return await _finalize_prepared_order(
        db,
        cart=cart,
        user=user,
        payload=payload,
        contact_info=contact_info,
        normalized_phone=normalized_phone,
        selected_delivery_service=selected_delivery_service,
        selected_delivery=resumed_selected_delivery,
        delivery_sum=resumed_delivery_sum,
        total=resumed_total,
        total_with_delivery=resumed_total_with_delivery,
        address_str=resumed_address_str,
        promo_code=resumed_promo_code,
        commentary_text=resumed_commentary_text,
        snapshot=resumed_snapshot,
    )


async def _prepare_order(payload: CheckoutData, db: AsyncSession) -> dict[str, object]:
    if not payload.contact_info:
        raise HTTPException(status_code=422, detail="contact_info is required")

    delivery_service = (payload.selected_delivery_service or "").strip()
    delivery_service_lower = delivery_service.lower()
    if delivery_service_lower not in {"cdek", "yandex"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery service")

    enriched_cart = await cart_json(payload.checkout_data, db=db)
    items = enriched_cart.get("items") or []
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    selected_delivery = deepcopy(payload.selected_delivery or {})
    selected_address_payload = selected_delivery.get("address")
    if isinstance(selected_address_payload, dict):
        await enrich_delivery_address_payload(selected_address_payload)
    delivery_sum = resolve_delivery_sum(payload.selected_delivery_service, selected_delivery).quantize(Q2, rounding=ROUND_HALF_UP)
    selected_delivery["delivery_sum"] = float(delivery_sum)

    contact_info = payload.contact_info.model_dump()
    normalized_phone = normalize_phone(contact_info["phone"]) or contact_info["phone"]
    contact_info["phone"] = normalized_phone
    commentary_text = _normalize_commentary_text(payload.commentary)
    address_str = normalize_address_for_cf(selected_delivery.get("address")) or "Не указан"

    user = await upsert_user(db, UserCreate(tg_id=payload.user_id))
    order_fingerprint = _build_order_fingerprint(
        user_id=user.tg_id,
        address_str=address_str,
        items=items,
    )
    existing_cart = await get_active_cart_by_order_fingerprint(db, order_fingerprint)
    if existing_cart:
        if _can_resume_incomplete_order(existing_cart):
            return await _resume_incomplete_order(
                db,
                cart=existing_cart,
                user=user,
                payload=payload,
                items=items,
                contact_info=contact_info,
                normalized_phone=normalized_phone,
                selected_delivery=selected_delivery,
                commentary_text=commentary_text,
                address_str=address_str,
            )
        _raise_duplicate_order(existing_cart.id)

    total = _to_decimal(enriched_cart.get("raw_total"))
    discountable_total = _to_decimal(enriched_cart.get("discountable_total"))
    total, promo_code = await _apply_promocode(db, total, discountable_total, payload.promocode)

    snapshot = _build_checkout_snapshot(
        payload,
        checkout_items=items,
        total=total,
        delivery_sum=delivery_sum,
        normalized_phone=normalized_phone,
        selected_delivery=selected_delivery,
        promocode=promo_code,
        commentary_text=commentary_text,
    )
    delivery_string = _delivery_string(payload.selected_delivery_service, address_str)
    total_with_delivery = (total + delivery_sum).quantize(Q2, rounding=ROUND_HALF_UP)

    try:
        cart = await create_cart(
            db,
            CartCreate(
                user_id=user.tg_id,
                phone=normalized_phone,
                email=contact_info["email"],
                sum=total,
                delivery_sum=delivery_sum,
                promo_code=promo_code,
                commentary=commentary_text,
                delivery_string=delivery_string,
                payment_method=payload.payment_method,
                payment_status="draft",
                amocrm_lead_id=None,
                order_fingerprint=order_fingerprint,
                selected_delivery_service=payload.selected_delivery_service,
                selected_delivery_payload=selected_delivery,
                checkout_snapshot=snapshot,
                status=amocrm.STATUS_WORDS.get(amocrm.STATUS_IDS["main"], "Создан"),
                is_active=True,
                is_paid=False,
                is_canceled=False,
                is_shipped=False,
            ),
        )
    except IntegrityError:
        await db.rollback()
        existing_cart = await get_active_cart_by_order_fingerprint(db, order_fingerprint)
        if existing_cart:
            if _can_resume_incomplete_order(existing_cart):
                return await _resume_incomplete_order(
                    db,
                    cart=existing_cart,
                    user=user,
                    payload=payload,
                    items=items,
                    contact_info=contact_info,
                    normalized_phone=normalized_phone,
                    selected_delivery=selected_delivery,
                    commentary_text=commentary_text,
                    address_str=address_str,
                )
            _raise_duplicate_order(existing_cart.id)
        raise

    cart = await _sync_cart_items(db, cart, items)
    return await _finalize_prepared_order(
        db,
        cart=cart,
        user=user,
        payload=payload,
        contact_info=contact_info,
        normalized_phone=normalized_phone,
        selected_delivery_service=payload.selected_delivery_service,
        selected_delivery=selected_delivery,
        delivery_sum=delivery_sum,
        total=total,
        total_with_delivery=total_with_delivery,
        address_str=address_str,
        promo_code=promo_code,
        commentary_text=commentary_text,
        snapshot=snapshot,
    )


async def reconcile_sbp_payment(
    db: AsyncSession,
    cart,
    *,
    payment_step: str | None = None,
    payment_status_code: int | None = None,
    payment_data: str | None = None,
    invoice_id: str | None = None,
) -> object:
    payment_status = _payment_status_from_code(payment_status_code) or _payment_status_from_step(payment_step)
    patch: dict[str, object] = {}
    if invoice_id:
        patch["payment_invoice_id"] = str(invoice_id)

    if payment_status == "paid":
        if cart.amocrm_lead_id:
            await amocrm.update_lead_status(int(cart.amocrm_lead_id), amocrm.STATUS_IDS["check_paid"])
        patch["payment_status"] = "paid"
        patch["payment_paid_at"] = _parse_payment_timestamp(payment_data) or datetime.now(timezone.utc)
        patch["payment_error"] = ""
    else:
        patch["payment_status"] = payment_status
        error_text = _payment_error_text(payment_status, payment_step)
        if error_text:
            patch["payment_error"] = error_text

    updated_cart = await update_cart(db, cart.id, CartUpdate(**patch))
    if payment_status == "paid":
        await sync_moysklad_customerorder_state(updated_cart, state_name=MOY_SKLAD_STATE_INVOICE_PAID)
        await sync_moysklad_invoiceout_state(updated_cart, state_name=MOY_SKLAD_INVOICEOUT_STATE_PAID)
    return updated_cart


def _status_payload(cart, *, payment_step: str | None = None, qr_url: str | None = None, qr_image: str | None = None) -> dict[str, object]:
    return {
        "status": "success",
        "order_number": cart.id,
        "payment_method": cart.payment_method,
        "payment_status": cart.payment_status,
        "payment_step": payment_step,
        "invoice_id": cart.payment_invoice_id,
        "qr_url": qr_url,
        "qr_image": qr_image,
        "is_paid": bool(cart.is_paid or cart.payment_status == "paid"),
        "can_retry": cart.payment_status in {"canceled", "error"},
    }


@router.post("/create", response_model=None)
async def create_payment(payload: CheckoutData, request: Request, db: AsyncSession = Depends(get_db)):
    prepared = await _prepare_order(payload, db)
    cart = prepared["cart"]
    user = prepared["user"]
    total_with_delivery = prepared["total_with_delivery"]
    contact_info = prepared["contact_info"]
    await sync_cart_to_moysklad_safe(db, cart=cart, user=user)

    payment_method = (payload.payment_method or "later").strip().lower()
    if payment_method == "later":
        cart = await update_cart(
            db,
            cart.id,
            CartUpdate(
                payment_method="later",
                payment_provider="manager",
                payment_status="pending",
                payment_error="",
            ),
        )
        return {
            "status": "success",
            "status_code": 202,
            "order_number": cart.id,
            "payment_method": "later",
            "payment_status": cart.payment_status,
        }

    if payment_method != "sbp":
        raise HTTPException(status_code=400, detail="Unsupported payment method")

    urls = _intellectmoney_urls(request, cart.id)
    success_url = urls["success_url"]
    fail_url = urls["fail_url"]
    back_url = urls["back_url"]
    result_url = urls["result_url"]
    ip_address = _detect_site_ip(request)
    user_name = _full_name(contact_info) or f"Заказ {cart.id}"

    cart = await update_cart(
        db,
        cart.id,
        CartUpdate(
            payment_method="sbp",
            payment_provider="intellectmoney",
            payment_status="created",
            payment_error="",
        ),
    )

    try:
        expire_at = datetime.now() + timedelta(minutes=30)
        create_invoice_result = await intellectmoney.create_invoice(
            order_id=str(cart.id),
            service_name=f"Заказ №{cart.id}",
            amount_rub=total_with_delivery,
            user_name=user_name,
            email=contact_info["email"],
            success_url=success_url,
            fail_url=fail_url,
            back_url=back_url,
            result_url=result_url,
            preference="Sbp",
        )
        result_payload = create_invoice_result.get("Result") or {}
        invoice_id = str(
            result_payload.get("InvoiceId")
            or result_payload.get("invoiceId")
            or create_invoice_result.get("InvoiceId")
            or ""
        )
        if not invoice_id:
            log.error("IntellectMoney createInvoice response missing InvoiceId | order_id=%s | response=%s", cart.id, create_invoice_result)
            raise IntellectMoneyError("IntellectMoney createInvoice succeeded without InvoiceId")

        cart = await update_cart(db, cart.id, CartUpdate(payment_invoice_id=invoice_id))

        sbp_result = await intellectmoney.sbp_payment(
            invoice_id=invoice_id,
            success_url=success_url,
            fail_url=fail_url,
            ip_address=ip_address,
        )
        parsed_sbp = intellectmoney.parse_payment_state(sbp_result)

        state_result = await intellectmoney.get_bank_card_payment_state(invoice_id=invoice_id)
        parsed_state = intellectmoney.parse_payment_state(state_result)
        payment_step = parsed_state["payment_step"] or parsed_sbp["payment_step"]
        qr_url = parsed_state["qr_url"] or parsed_sbp["qr_url"]
        qr_image = parsed_state["qr_image"] or parsed_sbp["qr_image"]

        if payment_step not in PENDING_PAYMENT_STEPS:
            cart = await reconcile_sbp_payment(
                db,
                cart,
                payment_step=payment_step,
                invoice_id=invoice_id,
            )
        else:
            cart = await update_cart(db, cart.id, CartUpdate(payment_status=_payment_status_from_step(payment_step)))
            await sync_moysklad_customerorder_state(cart, state_name=MOY_SKLAD_STATE_INVOICE_SENT)

        response = _status_payload(cart, payment_step=payment_step, qr_url=qr_url, qr_image=qr_image)
        response["expires_at"] = expire_at.replace(microsecond=0).isoformat()
        return response
    except IntellectMoneyError as exc:
        await update_cart(db, cart.id, CartUpdate(payment_status="error", payment_error=str(exc)))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Failed to initialize SBP payment for order %s", cart.id)
        await update_cart(db, cart.id, CartUpdate(payment_status="error", payment_error="Не удалось инициализировать СБП"))
        raise HTTPException(status_code=502, detail="Failed to initialize SBP payment") from exc


@router.get("/status", response_model=None)
async def get_payment_status(order_id: int, db: AsyncSession = Depends(get_db)):
    cart = await get_cart_by_id(db, order_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Order not found")

    payment_step = None
    qr_url = None
    qr_image = None

    if (
        (cart.payment_method or "").lower() == "sbp"
        and cart.payment_invoice_id
        and (cart.payment_status or "") not in FINAL_PAYMENT_STATUSES
    ):
        try:
            state_result = await intellectmoney.get_bank_card_payment_state(invoice_id=str(cart.payment_invoice_id))
            parsed_state = intellectmoney.parse_payment_state(state_result)
            payment_step = parsed_state["payment_step"]
            qr_url = parsed_state["qr_url"]
            qr_image = parsed_state["qr_image"]
            if payment_step:
                cart = await reconcile_sbp_payment(
                    db,
                    cart,
                    payment_step=payment_step,
                    invoice_id=str(cart.payment_invoice_id),
                )
                if payment_step in PENDING_PAYMENT_STEPS:
                    cart = await update_cart(db, cart.id, CartUpdate(payment_status=_payment_status_from_step(payment_step)))
                    await sync_moysklad_customerorder_state(cart, state_name=MOY_SKLAD_STATE_INVOICE_SENT)
        except IntellectMoneyError as exc:
            log.warning("IntellectMoney status check failed for order %s: %s", order_id, exc)

    return _status_payload(cart, payment_step=payment_step, qr_url=qr_url, qr_image=qr_image)

import asyncio
import logging
from typing import Any

from src.amocrm.client import amocrm
from src.internal_api.schemas import (
    InternalCartRead,
    InternalFeatureRead,
    InternalProductRead,
    InternalPromoRead,
    InternalUsedCodeRead,
    InternalUserRead,
)

logger = logging.getLogger("webapp.internal_api.serializers")


def _contact_enrichment_payload(user: Any, contact: dict[str, Any] | None) -> dict[str, Any]:
    contact_payload = amocrm.contact_payload(contact)
    name = str(contact_payload.get("name") or "").strip()
    surname = str(contact_payload.get("surname") or "").strip()
    full_name = " ".join(part for part in [name, surname] if part).strip() or "Без имени"
    email = str(contact_payload.get("email") or "").strip()
    phone = str(contact_payload.get("phone") or "").strip()
    tg_phone = str(getattr(user, "tg_phone", "") or "").strip() or "Отсутствует"
    return {
        "name": name,
        "surname": surname,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "contact_info": (
            f"ID ТГ: {user.tg_id}, "
            f"Номер ТГ: {tg_phone}, "
            f"Почта: {email or 'Отсутствует'}, "
            f"Номер телефона для покупок: {phone or 'Отсутствует'}"
        ),
    }


def serialize_user(user: Any, *, enrichment: dict[str, Any] | None = None) -> InternalUserRead | None:
    if not user:
        return None
    payload = {
        "tg_id": user.tg_id,
        "tg_ref_id": user.tg_ref_id,
        "tg_phone": user.tg_phone,
        "photo_url": user.photo_url,
        "contact_id": user.contact_id,
        "premium_requests": user.premium_requests,
        "premium_until": user.premium_until,
        "conversation_id": user.conversation_id,
        "last_used": user.last_used,
        "input_tokens": user.input_tokens,
        "output_tokens": user.output_tokens,
        "blocked_until": user.blocked_until,
        "utm_source": getattr(user, "utm_source", None),
        "utm_medium": getattr(user, "utm_medium", None),
        "utm_campaign": getattr(user, "utm_campaign", None),
        "utm_content": getattr(user, "utm_content", None),
        "utm_creative": getattr(user, "utm_creative", None),
        "utm_payload_raw": getattr(user, "utm_payload_raw", None),
        "created_at": getattr(user, "created_at", None),
        "updated_at": getattr(user, "updated_at", None),
    }
    if enrichment:
        payload.update(enrichment)
    return InternalUserRead.model_validate(payload)


async def serialize_user_enriched(user: Any) -> InternalUserRead | None:
    if not user:
        return None

    enrichment: dict[str, Any] | None = None
    if getattr(user, "contact_id", None):
        try:
            contact = await amocrm.get_contact(int(user.contact_id))
            enrichment = _contact_enrichment_payload(user, contact)
        except Exception:
            logger.exception("Failed to fetch amoCRM contact for user %s", user.tg_id)

    return serialize_user(user, enrichment=enrichment)


async def serialize_users_enriched(users: list[Any]) -> list[InternalUserRead]:
    if not users:
        return []

    contact_ids = [int(contact_id) for contact_id in {getattr(user, "contact_id", None) for user in users} if contact_id]
    contacts_by_id: dict[int, dict[str, Any] | None] = {}

    if contact_ids:
        results = await asyncio.gather(*(amocrm.get_contact(contact_id) for contact_id in contact_ids), return_exceptions=True)
        for contact_id, result in zip(contact_ids, results):
            if isinstance(result, Exception):
                logger.warning("Failed to fetch amoCRM contact for user search result %s: %s", contact_id, result)
                contacts_by_id[contact_id] = None
            else:
                contacts_by_id[contact_id] = result

    serialized: list[InternalUserRead] = []
    for user in users:
        enrichment: dict[str, Any] | None = None
        contact_id = getattr(user, "contact_id", None)
        if contact_id:
            contact = contacts_by_id.get(int(contact_id))
            if contact:
                enrichment = _contact_enrichment_payload(user, contact)

        item = serialize_user(user, enrichment=enrichment)
        if item:
            serialized.append(item)

    return serialized


def serialize_feature(feature: Any) -> InternalFeatureRead:
    return InternalFeatureRead.model_validate(
        {
            "onec_id": feature.onec_id,
            "product_onec_id": feature.product_onec_id,
            "name": feature.name,
            "code": feature.code,
            "file_id": feature.file_id,
            "price": feature.price,
            "balance": feature.balance,
        }
    )


def serialize_product(product: Any) -> InternalProductRead | None:
    if not product:
        return None
    return InternalProductRead.model_validate(
        {
            "id": product.id,
            "onec_id": product.onec_id,
            "name": product.name,
            "code": product.code,
            "description": product.description,
            "usage": product.usage,
            "expiration": product.expiration,
            "category_onec_id": product.category_onec_id,
            "features": [serialize_feature(feature) for feature in (product.features or [])],
        }
    )


def serialize_promo(promo: Any) -> InternalPromoRead | None:
    if not promo:
        return None
    return InternalPromoRead.model_validate(
        {
            "id": promo.id,
            "code": promo.code,
            "discount_pct": promo.discount_pct,
            "owner_name": promo.owner_name,
            "owner_pct": promo.owner_pct,
            "owner_amount_gained": promo.owner_amount_gained,
            "lvl1_name": promo.lvl1_name,
            "lvl1_pct": promo.lvl1_pct,
            "lvl1_amount_gained": promo.lvl1_amount_gained,
            "lvl2_name": promo.lvl2_name,
            "lvl2_pct": promo.lvl2_pct,
            "lvl2_amount_gained": promo.lvl2_amount_gained,
            "times_used": promo.times_used,
            "created_at": promo.created_at,
            "updated_at": promo.updated_at,
        }
    )


def serialize_used_code(code: Any) -> InternalUsedCodeRead | None:
    if not code:
        return None
    return InternalUsedCodeRead.model_validate(
        {
            "id": code.id,
            "user_id": code.user_id,
            "code": code.code,
            "price": code.price,
        }
    )


def serialize_cart(cart: Any) -> InternalCartRead | None:
    if not cart:
        return None
    user = getattr(cart, "user", None)
    return InternalCartRead.model_validate(
        {
            "id": cart.id,
            "user_id": cart.user_id,
            "name": cart.name,
            "phone": cart.phone,
            "email": cart.email,
            "sum": cart.sum,
            "delivery_sum": cart.delivery_sum,
            "promo_code": cart.promo_code,
            "promo_gains": cart.promo_gains,
            "promo_gains_given": cart.promo_gains_given,
            "delivery_string": cart.delivery_string,
            "commentary": cart.commentary,
            "payment_method": cart.payment_method,
            "payment_provider": cart.payment_provider,
            "payment_status": cart.payment_status,
            "payment_invoice_id": cart.payment_invoice_id,
            "payment_paid_at": cart.payment_paid_at,
            "amocrm_lead_id": cart.amocrm_lead_id,
            "delivery_created_at": cart.delivery_created_at,
            "delivery_provider_ref": cart.delivery_provider_ref,
            "is_active": cart.is_active,
            "is_paid": cart.is_paid,
            "is_canceled": cart.is_canceled,
            "is_shipped": cart.is_shipped,
            "status": cart.status,
            "yandex_request_id": cart.yandex_request_id,
            "created_at": cart.created_at,
            "updated_at": cart.updated_at,
            "user": serialize_user(user) if user else None,
        }
    )
